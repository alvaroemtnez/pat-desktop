# SPDX-License-Identifier: GPL-3.0-or-later

import signal
import sys
from gettext import gettext as _

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, VERSION  # noqa: E402
from .backend import PatBackend, pat_version  # noqa: E402

SHORTCUTS = [
    ("win.reload", ["<Control>r", "F5"], _("Reload")),
    ("win.configure", ["<Control>comma"], _("Pat configuration")),
    ("win.zoom-in", ["<Control>plus", "<Control>equal"], _("Zoom in")),
    ("win.zoom-out", ["<Control>minus"], _("Zoom out")),
    ("win.zoom-reset", ["<Control>0"], _("Reset zoom")),
    ("win.show-log", ["<Control>l"], _("Show log")),
    ("window.close", ["<Control>w"], _("Close window")),
    ("app.quit", ["<Control>q"], _("Quit")),
]


class PatDesktop(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.backend = PatBackend()
        self.window = None
        GLib.set_application_name("Pat Desktop")

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Pat's web UI has no dark theme, so keep the window chrome light too.
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        for name, callback in (("about", self._about), ("quit", self._quit),
                               ("shortcuts", self._shortcuts)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, cb=callback: cb())
            self.add_action(action)
        for action, accels, _label in SHORTCUTS:
            self.set_accels_for_action(action, accels)
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_unix_signal)

    def do_activate(self):
        if not self.window:
            from .window import PatWindow
            self.window = PatWindow(self, self.backend)
            self.window.start()
        self.window.present()

    def do_shutdown(self):
        # Normally Pat is already stopped by the window; this covers the rest.
        if self.backend.state != "stopped":
            self.backend.stop_sync()
        Adw.Application.do_shutdown(self)

    def _on_unix_signal(self):
        self._quit()
        return GLib.SOURCE_CONTINUE

    def _quit(self):
        if self.window:
            self.window.quit()
        else:
            self.quit()

    def _about(self):
        about = Adw.AboutDialog(
            application_name="Pat Desktop",
            application_icon=APP_ID,
            version=VERSION,
            developer_name=_("Pat Desktop contributors"),
            license_type=Gtk.License.GPL_3_0,
            website="https://code.alvaroedo.io/alvaroemtnez/pat-desktop",
            issue_url="https://code.alvaroedo.io/alvaroemtnez/pat-desktop/issues",
            comments=_(
                "A desktop wrapper for Pat, the cross-platform Winlink client.\n\n"
                "Pat Desktop is an unofficial project, not affiliated with or "
                "endorsed by the Pat project or the Winlink Development Team."),
        )
        version = pat_version(self.backend.binary) if self.backend.binary else None
        about.set_debug_info(
            f"Pat Desktop {VERSION}\n{version or 'pat: not found'}\n"
            f"Pat binary: {self.backend.binary}\nListening on: "
            f"{self.backend.base_url if self.backend.port else '-'}\n")
        about.add_credit_section(_("Pat"), ["Martin Hebnes Pedersen (LA5NTA) and contributors "
                                            "https://github.com/la5nta/pat"])
        about.add_legal_section("Pat", "© Martin Hebnes Pedersen (LA5NTA)",
                                Gtk.License.MIT_X11, None)
        about.present(self.window)

    def _shortcuts(self):
        dialog = Adw.Dialog(title=_("Keyboard Shortcuts"), content_width=420)
        group = Adw.PreferencesGroup()
        for _action, accels, label in SHORTCUTS:
            row = Adw.ActionRow(title=label)
            row.add_suffix(Gtk.ShortcutLabel(accelerator=accels[0], valign=Gtk.Align.CENTER))
            group.add(row)
        page = Adw.PreferencesPage()
        page.add(group)
        toolbar = Adw.ToolbarView(content=page)
        toolbar.add_top_bar(Adw.HeaderBar())
        dialog.set_child(toolbar)
        dialog.present(self.window)


def main():
    return PatDesktop().run(sys.argv)
