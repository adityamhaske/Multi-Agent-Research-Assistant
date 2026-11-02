"""G-2 on Windows (WebView2) and Linux (WebKitGTK): the installed app's folder handling,
driven through its own webview (internal/rfcs/V3.1-corpus-scope.md §14.1).

`tauri-driver` launches the installed application and forwards W3C WebDriver to the native
driver of that platform's webview, so the page steps run in the app a user installs. What
WebDriver cannot do is done with real operating-system input (`g2_os`):

- **The native folder picker.** WebKitGTK suppresses file choosers inside a WebDriver
  session, so on Linux the picker steps run against the app launched on its own, with real
  clicks and keys, and are checked in the project's corpus store. A cancel only passes when
  the picker was seen to open.
- **Dropping a folder.** No WebDriver can drag from another application, and a synthetic
  drop event cannot carry a directory, so a small native window offers the folder and the
  real pointer drags it onto the app. The shell's own drop handler once swallowed every drop
  while all synthetic tests passed; only a real drop shows that.

Every step records PASS, FAIL, OBSERVED or NOT RUN, with a screenshot. The evidence directory
gets `log.json`, `log.md` and the screenshots.

    python scripts/gates/g2_webview_e2e.py --app <installed binary> --work <dir> --out <dir>
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g2_os  # noqa: E402

DRIVER = "http://127.0.0.1:4444"
WINDOWS = g2_os.WINDOWS
MAIN_TITLE = r"^Research Assistant$"
NOT_PICKER = r"^(Research Assistant|G2 drag source)$"
PICKER = r"(?i)(select|open|upload|choose|folder)"


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
        self.id = _call("POST", "/session", caps, timeout=180)["sessionId"]

    def _p(self, suffix: str) -> str:
        return f"/session/{self.id}{suffix}"

    def find(self, xpath: str, timeout: float = 30) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            try:
                return _call(
                    "POST", self._p("/element"), {"using": "xpath", "value": xpath}, timeout=30
                )
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

    def rect(self, element: dict) -> dict:
        return _call("GET", self._p(f"/element/{_id(element)}/rect"))

    def script(self, js: str, *args):
        return _call("POST", self._p("/execute/sync"), {"script": js, "args": list(args)})

    def text(self) -> str:
        return self.script("return document.body.innerText") or ""

    def screenshot(self, path: Path) -> None:
        path.write_bytes(base64.b64decode(_call("GET", self._p("/screenshot"))))

    def close(self) -> None:
        try:
            _call("DELETE", self._p(""), timeout=60)
        except Exception:  # noqa: BLE001 — closing is best effort; the log is written anyway
            pass
        time.sleep(3)


class Log:
    def __init__(self, out: Path):
        self.out = out
        self.rows: list[dict] = []
        self.header: dict = {}

    def record(self, step: str, result: str, observed: str, shot: str | None = None) -> None:
        self.rows.append({"step": step, "result": result, "observed": observed, "screenshot": shot})
        print(f"[{result}] {step}: {observed}", flush=True)

    def write(self) -> None:
        (self.out / "log.json").write_text(
            json.dumps({**self.header, "steps": self.rows}, indent=1), encoding="utf-8"
        )
        lines = [f"# G-2 {self.header.get('platform')} — scripted webview pass", ""]
        lines += [f"- **{k}:** {v}" for k, v in self.header.items() if k != "platform"]
        lines += ["", "| # | Step | Observed | Result | Screenshot |", "|---|---|---|---|---|"]
        for n, r in enumerate(self.rows, start=1):
            lines.append(
                f"| {n} | {r['step']} | {r['observed']} | {r['result']} | {r['screenshot'] or ''} |"
            )
        (self.out / "log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── The corpus store, read directly where no WebDriver session is open ────────────


def store_tree(home: Path) -> dict[str, list[str]]:
    """folder name → the files filed in it, from every project store under this home."""
    tree: dict[str, list[str]] = {}
    for db in (home / ".research-engine" / "corpus").glob("corpus_*.sqlite"):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for folder, name in conn.execute(
                "SELECT f.name, m.display_name FROM corpus_folders f "
                "LEFT JOIN corpus_memberships m ON m.folder_id = f.id"
            ):
                tree.setdefault(folder, [])
                if name:
                    tree[folder].append(name)
        finally:
            conn.close()
    return tree


def wait_for(predicate, timeout: float = 120, every: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(every)
    return False


def picker_windows() -> list:
    import re

    return [w for w in g2_os.windows_titled(PICKER) if not re.match(NOT_PICKER, w[1])]


# ── Page helpers ──────────────────────────────────────────────────────────────────

DROP_ZONE = (
    "//p[contains(.,'Drag & drop files')]/ancestor::div[contains(@class,'border-dashed')][1]"
)


def queue_summary(s: Session) -> str:
    return (
        s.script(
            "const h=[...document.querySelectorAll('*')].find(e=>/^Upload queue/i.test("
            "(e.textContent||'').trim()) && e.children.length===0);return h?h.textContent:''"
        )
        or ""
    )


def wait_queue_done(s: Session, timeout: float = 300) -> str:
    def done():
        t = s.text()
        return bool(queue_summary(s)) and "Stop uploading" not in t and "Stopping" not in t

    wait_for(done, timeout)
    return queue_summary(s)


def open_corpus(s: Session) -> None:
    s.click(s.find("//a[normalize-space()='Corpus']", timeout=90))
    s.find("//button[normalize-space()='Choose folder']", timeout=60)
    time.sleep(1)


def center_on_screen(s: Session, element: dict) -> tuple[int, int]:
    (handle, _), *_ = g2_os.windows_titled(MAIN_TITLE)
    ox, oy = g2_os.client_origin(handle)
    r = s.rect(element)
    return int(ox + r["x"] + r["width"] / 2), int(oy + r["y"] + r["height"] / 2)


def start_drag_source(folder: Path) -> subprocess.Popen:
    if WINDOWS:
        cmd = [
            "powershell",
            "-NoProfile",
            "-STA",
            "-File",
            str(Path(__file__).with_name("g2_drag_source_win.ps1")),
            str(folder),
        ]
    else:
        cmd = [
            "/usr/bin/python3",
            str(Path(__file__).with_name("g2_drag_source_gtk.py")),
            str(folder),
        ]
    proc = subprocess.Popen(cmd)
    wait_for(lambda: bool(g2_os.windows_titled(r"^G2 drag source$")), timeout=30)
    time.sleep(1)
    return proc


def drag_source_point() -> tuple[int, int] | None:
    windows = g2_os.windows_titled(r"^G2 drag source$")
    if not windows:
        return None
    x, y = g2_os.client_origin(windows[0][0])
    return x + 100, y + 40


# ── Steps ─────────────────────────────────────────────────────────────────────────


def picker_cancel(log: Log, out: Path, open_picker, nothing_uploaded) -> None:
    """Open the native folder picker with a real click, see it, press Escape, see it go."""
    open_picker()
    seen = wait_for(lambda: bool(picker_windows()), timeout=15)
    titles = [t for _, t in picker_windows()]
    g2_os.screenshot(out / "01-native-picker-open.png")
    if not seen:
        log.record(
            "Choose folder opens the native picker",
            "FAIL",
            "no picker window appeared",
            "01-native-picker-open.png",
        )
        return
    g2_os.key("Escape")
    gone = wait_for(lambda: not picker_windows(), timeout=15)
    time.sleep(2)
    g2_os.screenshot(out / "02-after-picker-cancel.png")
    ok = gone and nothing_uploaded()
    log.record(
        "Choose folder, then cancel the native picker",
        "PASS" if ok else "FAIL",
        f"picker {titles} opened; after Escape it {'closed' if gone else 'stayed open'}; "
        f"{'nothing uploaded' if nothing_uploaded() else 'an upload started'}",
        "01-native-picker-open.png, 02-after-picker-cancel.png",
    )


def drop_folder(log: Log, out: Path, folder: Path, target: tuple[int, int], landed) -> None:
    source = start_drag_source(folder)
    try:
        start = drag_source_point()
        if start is None:
            log.record(
                "Drop a folder from another application",
                "NOT RUN",
                "the drag source window did not appear",
            )
            return
        g2_os.drag(start, target)
        ok = wait_for(landed, timeout=120)
        g2_os.screenshot(out / "06-after-drop.png")
        log.record(
            f"Drag folder {folder.name} (with a subfolder) from another application and drop it",
            "PASS" if ok else "FAIL",
            "uploaded with its subfolder" if ok else "nothing arrived from the drop",
            "06-after-drop.png",
        )
    finally:
        source.terminate()


def page_steps(s: Session, log: Log, out: Path, work: Path, downloads: Path) -> None:
    """Steps WebDriver can drive on every platform: the delete confirmation, preview and
    download with the app's token, a token-less engine request, and Stop uploading."""
    if s.exists("//button[@aria-label='Delete Thesis']"):
        s.click(s.find("//button[@aria-label='Delete Thesis']"))
        said = s.script("return arguments[0].innerText", s.find("//*[@role='alertdialog']"))
        s.screenshot(out / "07-delete-confirmation.png")
        ok = "3 subfolders" in said and "3 files" in said
        log.record(
            "Delete on folder Thesis (then Cancel)",
            "PASS" if ok else "FAIL",
            " ".join(said.split())[:220],
            "07-delete-confirmation.png",
        )
        s.click(s.find("//*[@role='alertdialog']//button[normalize-space()='Cancel']"))
    else:
        log.record("Delete on folder Thesis", "NOT RUN", "no Thesis folder to delete")

    status = s.script(
        "return fetch(window.__DESKTOP__.baseUrl + '/api/v1/corpus/documents').then(r=>r.status)"
    )
    log.record(
        "Engine without the app's token", "PASS" if status == 401 else "FAIL", f"HTTP {status}"
    )

    row = "//*[normalize-space()='solar.md']/ancestor::*[.//button[normalize-space()='Preview']][1]"
    if s.exists(row):
        s.click(s.find(row + "//button[normalize-space()='Preview']"))
        s.find("//*[@role='dialog' and contains(@aria-label,'solar.md')]")
        time.sleep(1)
        shown = "Solar cells convert sunlight" in s.text()
        s.screenshot(out / "08-preview.png")
        log.record(
            "Preview solar.md",
            "PASS" if shown else "FAIL",
            "the file's text is shown" if shown else "no text",
            "08-preview.png",
        )
        before = set(downloads.glob("solar*")) if downloads.exists() else set()
        s.click(s.find("//*[@role='dialog']//a[normalize-space()='Download']"))
        wait_for(lambda: bool(set(downloads.glob("solar*")) - before), timeout=20)
        new = sorted((set(downloads.glob("solar*")) if downloads.exists() else set()) - before)
        source = work / "Thesis" / "ch1" / "notes" / "solar.md"
        same = bool(new) and new[0].read_bytes() == source.read_bytes()
        s.screenshot(out / "09-download.png")
        log.record(
            "Download from the preview",
            "PASS" if same else "FAIL",
            f"{new[0].name}, identical to the source"
            if same
            else f"no file appeared in {downloads}",
            "09-download.png",
        )
        s.click(s.find("//*[@role='dialog']//button[normalize-space()='Close']"))
    else:
        log.record("Preview and download", "NOT RUN", "solar.md was not uploaded")

    try:
        files = "\n".join(str(p) for p in sorted((work / "big").iterdir()))
        s.send_keys(s.find("//input[@type='file' and not(@webkitdirectory)]"), files)
        s.click(s.find("//button[normalize-space()='Stop uploading']", timeout=60))
        summary = wait_queue_done(s, timeout=600)
        body = s.text()
        skipped = "skipped" in body.lower()
        s.screenshot(out / "10-stopped.png")
        log.record(
            "Upload 40 large files, press Stop uploading",
            "PASS" if skipped and "40/40" not in summary else "FAIL",
            f"{summary}; files marked skipped: {skipped}",
            "10-stopped.png",
        )
    except WebDriverError as exc:
        log.record("Stop uploading part-way", "NOT RUN", str(exc)[:200])


# ── Platforms ─────────────────────────────────────────────────────────────────────


def run_windows(app: str, work: Path, out: Path, downloads: Path, log: Log) -> None:
    s = Session(app)
    try:
        open_corpus(s)
        log.header["engine"] = engine_version(s)
        s.screenshot(out / "00-corpus-page.png")
        choose = s.find("//button[normalize-space()='Choose folder']")

        def open_picker():
            threading.Thread(target=lambda: s.click(choose), daemon=True).start()

        picker_cancel(log, out, open_picker, lambda: not queue_summary(s))

        # WebView2's driver hands a directory to the folder input itself, so the nested
        # upload goes through the input rather than the picker's own folder field.
        s.send_keys(s.find("//input[@webkitdirectory]"), str(work / "Thesis"))
        summary = wait_queue_done(s)
        body = s.text()
        nested = all(
            p in body
            for p in ("Thesis/ch1/intro.txt", "Thesis/ch1/notes/solar.md", "Thesis/ch2/wind.txt")
        )
        s.screenshot(out / "03-nested-folder.png")
        log.record(
            "Upload a nested folder (handed to the folder input by the driver)",
            "PASS" if nested else "FAIL",
            f"{summary}; relative paths kept: {nested}",
            "03-nested-folder.png",
        )
        log.record(
            "Unreadable subfolder Thesis/locked (an icacls deny)",
            "OBSERVED",
            "its file was uploaded"
            if "hidden.txt" in body
            else "left out of the upload, with no message to the user",
            "03-nested-folder.png",
        )

        target = center_on_screen(s, s.find(DROP_ZONE))
        drop_folder(
            log,
            out,
            work / "dropsrc" / "Dropped",
            target,
            lambda: "Dropped/inner/deep.txt" in s.text(),
        )

        page_steps(s, log, out, work, downloads)
    finally:
        s.close()


def run_linux(app: str, work: Path, out: Path, downloads: Path, home: Path, log: Log) -> None:
    # Measure the page under WebDriver: positions are the same in any launch at this size.
    s = Session(app)
    try:
        nav = center_on_screen(s, s.find("//a[normalize-space()='Corpus']", timeout=90))
        open_corpus(s)
        log.header["engine"] = engine_version(s)
        s.screenshot(out / "00-corpus-page.png")
        (handle, _), *_ = g2_os.windows_titled(MAIN_TITLE)
        origin = g2_os.client_origin(handle)
        rel = lambda p: (p[0] - origin[0], p[1] - origin[1])  # noqa: E731
        choose_rel = rel(center_on_screen(s, s.find("//button[normalize-space()='Choose folder']")))
        drop_rel = rel(center_on_screen(s, s.find(DROP_ZONE)))
        nav_rel = rel(nav)
    finally:
        s.close()

    # The picker and the drop, on the app launched on its own (no WebDriver session).
    env = {**os.environ, "OLLAMA_BASE_URL": "http://127.0.0.1:11434/v1"}
    proc = subprocess.Popen([app], env=env)
    try:
        wait_for(lambda: bool(g2_os.windows_titled(MAIN_TITLE)), timeout=90)
        time.sleep(8)
        (handle, _), *_ = g2_os.windows_titled(MAIN_TITLE)
        ox, oy = g2_os.client_origin(handle)
        at = lambda p: (ox + p[0], oy + p[1])  # noqa: E731
        g2_os.click(*at(nav_rel))
        time.sleep(4)
        before = store_tree(home)

        picker_cancel(
            log, out, lambda: g2_os.click(*at(choose_rel)), lambda: store_tree(home) == before
        )

        g2_os.click(*at(choose_rel))
        if wait_for(lambda: bool(picker_windows()), timeout=15):
            g2_os.key("ctrl+l")
            time.sleep(0.5)
            g2_os.type_text(str(work / "Thesis"))
            time.sleep(0.5)
            g2_os.screenshot(out / "03a-picker-path-typed.png")
            g2_os.key("Return")
            time.sleep(2)
            if picker_windows():
                g2_os.key("Return")  # the first Return may only open the folder
            want = {"Thesis", "ch1", "ch2", "notes"}
            ok = wait_for(lambda: want <= set(store_tree(home)), timeout=180)
            time.sleep(3)
            tree = store_tree(home)
            g2_os.screenshot(out / "03-nested-folder.png")
            log.record(
                "Choose folder → pick Thesis in the native picker",
                "PASS" if ok else "FAIL",
                f"folders in the store: {sorted(tree)}; files: "
                f"{ {k: sorted(v) for k, v in tree.items() if k in want} }",
                "03a-picker-path-typed.png, 03-nested-folder.png",
            )
            files = [f for names in tree.values() for f in names]
            log.record(
                "Unreadable subfolder Thesis/locked (chmod 000)",
                "OBSERVED",
                "its file was uploaded"
                if "hidden.txt" in files
                else "left out of the upload, with no message to the user",
                "03-nested-folder.png",
            )
        else:
            g2_os.screenshot(out / "03-nested-folder.png")
            log.record(
                "Choose folder → pick Thesis in the native picker",
                "FAIL",
                "no picker window appeared",
                "03-nested-folder.png",
            )

        drop_folder(
            log,
            out,
            work / "dropsrc" / "Dropped",
            at(drop_rel),
            lambda: {"Dropped", "inner"} <= set(store_tree(home)),
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(3)

    s = Session(app)
    try:
        open_corpus(s)
        page_steps(s, log, out, work, downloads)
    finally:
        s.close()


def engine_version(s: Session):
    return s.script(
        "return fetch(window.__DESKTOP__.baseUrl + '/api/v1/version',"
        "{headers:{Authorization:'Bearer '+window.__DESKTOP__.token}}).then(r=>r.json())"
    )


def make_fixtures(root: Path) -> None:
    """The same tree the macOS pass used, so the three platforms are compared like for like."""
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    files = {
        "Thesis/ch1/intro.txt": "Chapter one says retrieval augments generation with documents.\n",
        "Thesis/ch1/notes/solar.md": "# Notes\nSolar cells convert sunlight into electricity.\n",
        "Thesis/ch2/wind.txt": "Chapter two: wind farms had a capacity factor of 34 percent.\n",
        "Thesis/locked/hidden.txt": "secret\n",
        "dropsrc/Dropped/top.txt": "Dropped folder top file about tidal energy.\n",
        "dropsrc/Dropped/inner/deep.txt": "Inner file about geothermal plants.\n",
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
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    args = parser.parse_args()
    make_fixtures(args.work)
    args.out.mkdir(parents=True, exist_ok=True)
    log = Log(args.out)
    log.header = {
        "platform": "Windows (WebView2)" if WINDOWS else "Linux (WebKitGTK)",
        "app": args.app,
        "embeddings": "scripts/gates/g2_embed_stub.py (no Ollama on a runner)",
    }
    try:
        if WINDOWS:
            run_windows(args.app, args.work, args.out, args.downloads, log)
        else:
            run_linux(args.app, args.work, args.out, args.downloads, Path.home(), log)
    except Exception as exc:  # noqa: BLE001 — recorded, then the run fails
        g2_os.screenshot(args.out / "99-error.png")
        log.record("Unexpected error", "FAIL", f"{type(exc).__name__}: {exc}"[:400], "99-error.png")
    finally:
        log.write()
    return 1 if any(r["result"] in ("FAIL", "NOT RUN") for r in log.rows) else 0


if __name__ == "__main__":
    sys.exit(main())
