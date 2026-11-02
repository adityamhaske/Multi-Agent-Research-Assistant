"""A GTK window that offers one folder as a drag source, the way a file manager does.

Run with the system Python (python3-gi); `g2_os.drag` moves the real pointer from it onto the
app, so the drop arrives through X11's own drag protocol as a user's would.

    /usr/bin/python3 scripts/gates/g2_drag_source_gtk.py <folder>
"""

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

folder = Path(sys.argv[1]).resolve()

window = Gtk.Window(title="G2 drag source")
window.set_default_size(240, 120)
window.move(40, 40)
button = Gtk.Button(label=f"Drag {folder.name}")
button.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY)
button.drag_source_add_uri_targets()
button.connect("drag-data-get", lambda _w, _c, data, _i, _t: data.set_uris([folder.as_uri()]))
window.add(button)
window.connect("destroy", Gtk.main_quit)
window.show_all()
Gtk.main()
