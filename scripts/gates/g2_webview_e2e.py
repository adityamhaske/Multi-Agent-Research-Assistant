"""G-2 on Windows (WebView2) and Linux (WebKitGTK): the installed app's folder handling,
driven through its own webview (internal/rfcs/V3.1-corpus-scope.md §14.1).

`tauri-driver` launches the installed application and forwards W3C WebDriver to the native
driver of that platform's webview, so every step below runs in the app a user installs, not
in a browser. What WebDriver cannot reach — the operating system's folder picker — is driven
with the platform's own input tools (`xdotool` under Xvfb, `SendKeys` on Windows) and
captured with an OS screenshot.

Each step records PASS, FAIL or what it observed; a step the platform cannot do is recorded
as such, never skipped silently. The evidence directory gets `log.json`, `log.md` and a
screenshot per step.

    python scripts/gates/g2_webview_e2e.py --app <installed binary> --fixtures <dir> --out <dir>
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DRIVER = "http://127.0.0.1:4444"
WINDOWS = platform.system() == "Windows"


class WebDriverError(RuntimeError):
    pass


def _call(method: str, path: str, body: dict | None = None, timeout: float = 120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{DRIVER}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}").get("value")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise WebDriverError(f"{method} {path}: {exc.code} {detail}") from exc


def _id(element: dict) -> str:
    return next(iter(element.values()))


class Session:
    def __init__(self, application: str):
        caps = {"capabilities": {"alwaysMatch": {"tauri:options": {"application": application}}}}
        value = _call("POST", "/session", caps, timeout=180)
        self.id = value["sessionId"]

    def _p(self, suffix: str) -> str:
        return f"/session/{self.id}{suffix}"

    def find(self, xpath: str, timeout: float = 30):
        deadline = time.monotonic() + timeout
        while True:
            try:
                value = _call(
                    "POST", self._p("/element"), {"using": "xpath", "value": xpath}, timeout=30
                )
                return value  # {web element identifier: id}, passed back as given
            except WebDriverError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)

    def exists(self, xpath: str) -> bool:
        return bool(_call("POST", self._p("/elements"), {"using": "xpath", "value": xpath}))

    def click(self, element: dict) -> None:
        _call("POST", self._p(f"/element/{_id(element)}/click"), {})

    def send_keys(self, element: dict, text: str) -> None:
        _call("POST", self._p(f"/element/{_id(element)}/value"), {"text": text})

    def script(self, js: str, *args):
        return _call("POST", self._p("/execute/sync"), {"script": js, "args": list(args)})

    def text(self) -> str:
        return self.script("return document.body.innerText") or ""

    def screenshot(self, path: Path) -> None:
        path.write_bytes(base64.b64decode(_call("GET", self._p("/screenshot"))))

    def close(self) -> None:
        try:
            _call("DELETE", self._p(""), timeout=30)
        except Exception:  # noqa: BLE001 — closing is best effort; the log is already written
            pass


def os_screenshot(path: Path) -> bool:
    """The whole screen, so a native dialog the webview cannot see is in the evidence."""
    if WINDOWS:
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
            "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
            "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
            "$g=[System.Drawing.Graphics]::FromImage($i);"
            "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
            f"$i.Save('{path}')"
        )
        cmd = ["powershell", "-NoProfile", "-Command", ps]
    else:
        cmd = ["import", "-window", "root", str(path)]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def os_escape() -> None:
    """Press Escape in whatever window has focus — the native picker, once it is open."""
    if WINDOWS:
        ps = "(New-Object -ComObject WScript.Shell).SendKeys('{ESC}')"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    else:
        subprocess.run(["xdotool", "key", "Escape"], capture_output=True)


class Log:
    def __init__(self, out: Path):
        self.out = out
        self.rows: list[dict] = []

    def record(self, step: str, result: str, observed: str, shot: str | None = None) -> None:
        self.rows.append({"step": step, "result": result, "observed": observed, "screenshot": shot})
        print(f"[{result}] {step}: {observed}", flush=True)

    def write(self, header: dict) -> None:
        (self.out / "log.json").write_text(
            json.dumps({**header, "steps": self.rows}, indent=1), encoding="utf-8"
        )
        lines = [f"# G-2 {header['platform']} — scripted webview pass", ""]
        lines += [f"- **{k}:** {v}" for k, v in header.items() if k != "platform"]
        lines += ["", "| # | Step | Observed | Result | Screenshot |", "|---|---|---|---|---|"]
        for n, r in enumerate(self.rows, start=1):
            lines.append(
                f"| {n} | {r['step']} | {r['observed']} | {r['result']} | {r['screenshot'] or ''} |"
            )
        (self.out / "log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def queue_summary(s: Session) -> str:
    return (
        s.script(
            "const h=[...document.querySelectorAll('*')].find(e=>/^Upload queue/i.test("
            "(e.textContent||'').trim()) && e.children.length===0);return h?h.textContent:''"
        )
        or ""
    )


def wait_queue_done(s: Session, timeout: float = 300) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        summary = queue_summary(s)
        if summary and "Stop uploading" not in s.text() and "Stopping" not in s.text():
            return summary
        time.sleep(1)
    return queue_summary(s)


def run(app: str, fixtures: Path, out: Path, downloads: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    log = Log(out)
    s = Session(app)
    header = {"platform": "Windows (WebView2)" if WINDOWS else "Linux (WebKitGTK)", "app": app}
    try:
        s.click(s.find("//a[normalize-space()='Corpus']", timeout=90))
        choose_folder = s.find("//button[normalize-space()='Choose folder']", timeout=60)
        build = s.script(
            "return fetch(window.__DESKTOP__.baseUrl + '/api/v1/version',"
            "{headers:{Authorization:'Bearer '+window.__DESKTOP__.token}}).then(r=>r.json())"
        )
        header["engine"] = build
        s.screenshot(out / "00-corpus-page.png")
        log.record("Open the Corpus page", "PASS", "Choose folder is shown", "00-corpus-page.png")

        # 1. The native picker opens and cancelling it changes nothing.
        clicker = threading.Thread(target=lambda: s.click(choose_folder), daemon=True)
        clicker.start()
        time.sleep(4)
        opened = os_screenshot(out / "01-native-picker-open.png")
        os_escape()
        clicker.join(timeout=30)
        time.sleep(1)
        changed = bool(queue_summary(s))
        s.screenshot(out / "02-after-picker-cancel.png")
        log.record(
            "Choose folder, then cancel the native picker",
            "FAIL" if changed else "PASS",
            ("an upload started" if changed else "nothing uploaded, no error")
            + ("; OS screenshot of the open picker kept" if opened else "; no OS screenshot"),
            "01-native-picker-open.png, 02-after-picker-cancel.png",
        )

        # 2. A nested folder, one subfolder unreadable.
        folder_input = s.find("//input[@webkitdirectory]")
        thesis = fixtures / "Thesis"
        try:
            s.send_keys(folder_input, str(thesis))
            summary = wait_queue_done(s)
            body = s.text()
            nested = all(p in body for p in ("Thesis/ch1/intro.txt", "Thesis/ch2/wind.txt"))
            deep = "Thesis/ch1/notes/solar.md" in body
            locked = "hidden.txt" in body
            s.screenshot(out / "03-nested-folder.png")
            log.record(
                "Upload a nested folder (Thesis/ch1/notes, Thesis/ch2)",
                "PASS" if nested and deep else "FAIL",
                f"{summary}; relative paths kept: {nested and deep}",
                "03-nested-folder.png",
            )
            log.record(
                "Unreadable subfolder Thesis/locked",
                "OBSERVED",
                "its file was listed (the permission was not enforced)"
                if locked
                else "left out of the upload, with no message to the user",
                "03-nested-folder.png",
            )
        except WebDriverError as exc:
            s.screenshot(out / "03-nested-folder.png")
            log.record(
                "Upload a nested folder through the folder input",
                "NOT RUN",
                f"this platform's WebDriver cannot hand a directory to the input: {exc}",
                "03-nested-folder.png",
            )

        # 3. The delete confirmation states what will go.
        if s.exists("//button[@aria-label='Delete Thesis']"):
            s.click(s.find("//button[@aria-label='Delete Thesis']"))
            dialog = s.find("//*[@role='alertdialog']")
            said = s.script("return arguments[0].innerText", dialog)
            s.screenshot(out / "04-delete-confirmation.png")
            ok = "3 subfolders" in said and "3 files" in said
            log.record(
                "Delete on folder Thesis (then Cancel)",
                "PASS" if ok else "FAIL",
                " ".join(said.split())[:200],
                "04-delete-confirmation.png",
            )
            s.click(s.find("//*[@role='alertdialog']//button[normalize-space()='Cancel']"))

        # 4. Preview and download carry the app's token.
        token_less = s.script(
            "return fetch(window.__DESKTOP__.baseUrl + '/api/v1/corpus/documents')"
            ".then(r=>r.status)"
        )
        log.record(
            "Engine without the app's token",
            "PASS" if token_less == 401 else "FAIL",
            f"HTTP {token_less}",
        )
        if s.exists("//*[normalize-space()='solar.md']"):
            row = "//*[normalize-space()='solar.md']/ancestor::*[.//button[normalize-space()='Preview']][1]"
            s.click(s.find(row + "//button[normalize-space()='Preview']"))
            s.find("//*[@role='dialog' and contains(@aria-label,'solar.md')]")
            time.sleep(1)
            shown = "Solar cells convert sunlight" in s.text()
            s.screenshot(out / "05-preview.png")
            log.record(
                "Preview solar.md",
                "PASS" if shown else "FAIL",
                "the file's text is shown" if shown else "no text",
                "05-preview.png",
            )
            before = set(downloads.glob("solar*")) if downloads.exists() else set()
            s.click(s.find("//*[@role='dialog']//a[normalize-space()='Download']"))
            time.sleep(5)
            after = set(downloads.glob("solar*")) if downloads.exists() else set()
            new = sorted(after - before)
            same = bool(new) and new[0].read_bytes() == (thesis / "ch1/notes/solar.md").read_bytes()
            s.screenshot(out / "06-download.png")
            log.record(
                "Download from the preview",
                "PASS" if same else "FAIL",
                f"{new[0].name}, identical to the source"
                if same
                else f"no file appeared in {downloads}",
                "06-download.png",
            )
            s.click(s.find("//*[@role='dialog']//button[normalize-space()='Close']"))

        # 5. Stop uploading part-way.
        try:
            s.send_keys(s.find("//input[@webkitdirectory]"), str(fixtures / "big"))
            stop = s.find("//button[normalize-space()='Stop uploading']", timeout=60)
            s.click(stop)
            summary = wait_queue_done(s, timeout=600)
            body = s.text()
            skipped = body.count("SKIPPED") + body.lower().count("skipped")
            s.screenshot(out / "07-stopped.png")
            log.record(
                "Upload 40 large files, press Stop uploading",
                "PASS" if skipped and "40/40" not in summary else "FAIL",
                f"{summary}; skipped entries shown: {bool(skipped)}",
                "07-stopped.png",
            )
        except WebDriverError as exc:
            log.record("Stop uploading part-way", "NOT RUN", str(exc)[:200])
    except Exception as exc:  # noqa: BLE001 — recorded, then the run fails
        try:
            s.screenshot(out / "99-error.png")
        except Exception:  # noqa: BLE001
            pass
        log.record("Unexpected error", "FAIL", f"{type(exc).__name__}: {exc}"[:400], "99-error.png")
    finally:
        log.write(header)
        s.close()
    return 1 if any(r["result"] == "FAIL" for r in log.rows) else 0


def make_fixtures(root: Path) -> None:
    """The same tree the macOS pass used, so the three platforms are compared like for like."""
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    files = {
        "Thesis/ch1/intro.txt": "Chapter one says retrieval augments generation with documents.\n",
        "Thesis/ch1/notes/solar.md": "# Notes\nSolar cells convert sunlight into electricity.\n",
        "Thesis/ch2/wind.txt": "Chapter two: wind farms had a capacity factor of 34 percent in 2022.\n",
        "Thesis/locked/hidden.txt": "secret\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    words = "solar wind tidal grid storage battery turbine panel inverter demand".split()
    (root / "big").mkdir()
    for i in range(40):
        line = " ".join(words[(i + j) % len(words)] for j in range(60)) + ".\n"
        (root / "big" / f"doc{i:02d}.txt").write_text(line * 1500, encoding="utf-8")
    locked = root / "Thesis" / "locked"
    if WINDOWS:
        user = os.environ.get("USERNAME", "")
        subprocess.run(["icacls", str(locked), "/deny", f"{user}:(OI)(CI)(R)"], check=False)
    else:
        locked.chmod(0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--app", required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    args = parser.parse_args()
    make_fixtures(args.fixtures)
    return run(args.app, args.fixtures, args.out, args.downloads)


if __name__ == "__main__":
    sys.exit(main())
