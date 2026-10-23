# SPDX-License-Identifier: GPL-3.0-or-later

from gettext import gettext as _

from gi.repository import Adw, Gdk, Gtk


class LogWindow(Adw.Window):
    """Live view of Pat's output, for troubleshooting radio and modem setups."""

    def __init__(self, parent, backend):
        super().__init__(transient_for=parent, title=_("Pat Log"),
                         default_width=800, default_height=500)
        self.buffer = Gtk.TextBuffer()
        self.buffer.set_text("\n".join(backend.log))
        view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=8, bottom_margin=8, left_margin=8, right_margin=8)
        self.scroller = Gtk.ScrolledWindow(child=view, vexpand=True)

        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text=_("Copy Log"))
        copy.connect("clicked", self._copy)
        header = Adw.HeaderBar()
        header.pack_start(copy)
        toolbar = Adw.ToolbarView(content=self.scroller)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

        self._handler = backend.connect("log-line", self._on_line)
        self.connect("destroy", lambda _w: backend.disconnect(self._handler))
        self.connect("map", lambda _w: self._scroll_to_end())

    def _on_line(self, _backend, line):
        adj = self.scroller.get_vadjustment()
        at_end = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 4
        self.buffer.insert(self.buffer.get_end_iter(), "\n" + line)
        if at_end:
            self._scroll_to_end()

    def _scroll_to_end(self):
        view = self.scroller.get_child()
        view.scroll_to_mark(self.buffer.get_insert(), 0, False, 0, 0)
        self.buffer.place_cursor(self.buffer.get_end_iter())
        view.scroll_to_mark(self.buffer.get_insert(), 0, False, 0, 0)

    def _copy(self, _button):
        start, end = self.buffer.get_bounds()
        Gdk.Display.get_default().get_clipboard().set(self.buffer.get_text(start, end, False))
