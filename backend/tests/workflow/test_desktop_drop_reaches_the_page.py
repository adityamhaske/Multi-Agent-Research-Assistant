"""
A folder dropped on the desktop app reaches the page (RFC V3.1 G-2).

The corpus page reads dropped files and folders from the page's own drop events
(`frontend/lib/dropFiles.ts`). Tauri 2 turns on a native drag-drop handler for every webview
unless told otherwise, and that handler takes the drop first: on the packaged macOS app the
drop zone never highlighted and a dropped folder uploaded nothing, while every web test and
the folder picker passed. No test can drive a native drag, so this pins the one line that
decides it — and its evidence is the launched-build pass in
`release-audit/v3.1.0/evidence/G-2/`.
"""

from __future__ import annotations

import re
from pathlib import Path

LIB_RS = Path(__file__).resolve().parents[3] / "desktop" / "src" / "lib.rs"


def test_the_main_window_leaves_drops_to_the_page():
    source = LIB_RS.read_text(encoding="utf-8")
    builder = re.search(r"WebviewWindowBuilder::new\(.*?\.build\(\)", source, re.S)
    assert builder, "the main window is no longer built in lib.rs; move this check with it"
    assert ".disable_drag_drop_handler()" in builder.group(0)
