"""Real operating-system input for the G-2 pass: what WebDriver cannot do.

WebDriver drives the page; it cannot press a key in a native dialog, and no WebDriver can
perform a drag from another application. A drop that the shell swallows before the page sees
it passes every synthetic test (the macOS pass found exactly that), so the drop here is a real
one: a small native window offers a folder as a drag source (`g2_drag_source_gtk.py`,
`g2_drag_source_win.ps1`) and this module moves the real pointer from it to the app.

Linux uses `xdotool` under Xvfb; Windows uses user32 through ctypes. Coordinates are screen
pixels at a scale of 1, which is what both runners have.
"""

from __future__ import annotations

import platform
import re
import subprocess
import time

WINDOWS = platform.system() == "Windows"

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _LEFTDOWN, _LEFTUP = 0x0002, 0x0004


def _xdotool(*args: str) -> str:
    return subprocess.run(["xdotool", *args], capture_output=True, text=True).stdout.strip()


def windows_titled(pattern: str) -> list[tuple[int, str]]:
    """Visible top-level windows whose title matches `pattern`, as (handle, title)."""
    rx = re.compile(pattern)
    found: list[tuple[int, str]] = []
    if WINDOWS:

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            if _user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(512)
                _user32.GetWindowTextW(hwnd, buf, 512)
                if buf.value and rx.search(buf.value):
                    found.append((int(hwnd), buf.value))
            return True

        _user32.EnumWindows(each, 0)
        return found
    for wid in _xdotool("search", "--onlyvisible", "--name", ".").split():
        title = _xdotool("getwindowname", wid)
        if title and rx.search(title):
            found.append((int(wid), title))
    return found


def client_origin(handle: int) -> tuple[int, int]:
    """Screen position of a window's client area: where its webview's (0, 0) is."""
    if WINDOWS:
        pt = wintypes.POINT(0, 0)
        _user32.ClientToScreen(handle, ctypes.byref(pt))
        return pt.x, pt.y
    shell = _xdotool("getwindowgeometry", "--shell", str(handle))
    values = dict(line.split("=", 1) for line in shell.splitlines() if "=" in line)
    return int(values["X"]), int(values["Y"])


def move_window(handle: int, x: int, y: int) -> None:
    if WINDOWS:
        _user32.SetWindowPos(handle, 0, x, y, 0, 0, 0x0001 | 0x0004)  # NOSIZE | NOZORDER
    else:
        _xdotool("windowmove", str(handle), str(x), str(y))


def click(x: int, y: int) -> None:
    if WINDOWS:
        _user32.SetCursorPos(x, y)
        _user32.mouse_event(_LEFTDOWN, 0, 0, 0, 0)
        _user32.mouse_event(_LEFTUP, 0, 0, 0, 0)
    else:
        _xdotool("mousemove", "--sync", str(x), str(y), "click", "1")


def drag(start: tuple[int, int], end: tuple[int, int], steps: int = 25) -> None:
    """Press at `start`, move in steps (a drag session needs motion to begin), hold over the
    target so it sees the drag, release at `end`."""
    if WINDOWS:
        _user32.SetCursorPos(*start)
        _user32.mouse_event(_LEFTDOWN, 0, 0, 0, 0)
    else:
        _xdotool("mousemove", "--sync", str(start[0]), str(start[1]))
        _xdotool("mousedown", "1")
    for i in range(1, steps + 1):
        x = start[0] + (end[0] - start[0]) * i // steps
        y = start[1] + (end[1] - start[1]) * i // steps
        if WINDOWS:
            _user32.SetCursorPos(x, y)
            _user32.mouse_event(0x0001, 0, 0, 0, 0)  # MOVE, so OLE's drag loop sees it
        else:
            _xdotool("mousemove", str(x), str(y))
        time.sleep(0.05)
    time.sleep(1)
    if WINDOWS:
        _user32.mouse_event(_LEFTUP, 0, 0, 0, 0)
    else:
        _xdotool("mouseup", "1")


def key(combo: str) -> None:
    """A key press for the focused window: `Escape`, `Return`, `ctrl+l` (xdotool names)."""
    if WINDOWS:
        sendkeys = {"Escape": "{ESC}", "Return": "{ENTER}"}.get(combo, combo)
        script = f"(New-Object -ComObject WScript.Shell).SendKeys('{sendkeys}')"
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)
    else:
        _xdotool("key", combo)


def type_text(text: str) -> None:
    if WINDOWS:
        escaped = re.sub(r"([+^%~(){}\[\]])", r"{\1}", text).replace("'", "''")
        script = f"(New-Object -ComObject WScript.Shell).SendKeys('{escaped}')"
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)
    else:
        _xdotool("type", "--delay", "20", text)


def screenshot(path) -> bool:
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
