# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings for the bundled modems and rigctld (see modems.py)."""

from gettext import gettext as _

from gi.repository import Adw, Gio, GLib, Gtk

from . import modems, varatables

SPEEDS = [0, 4800, 9600, 19200, 38400, 57600, 115200]
RIGCTLD_PTT_LABELS = {
    "cat": _("CAT command"),
    "rts": _("Serial RTS"),
    "dtr": _("Serial DTR"),
    "none": _("None (VOX)"),
}

INTRO = _(
    "Pat Desktop can run these modems for Pat. Each one listens where Pat's "
    "configuration expects that transport, and starts and stops with Pat. "
    "Their output goes to the log.\n\n"
    "PTT “Pat or VOX”: the modem leaves the radio alone, and Pat keys it through "
    "rig control, or the radio's VOX does. A sound card the desktop is using "
    "may be busy; the system default goes through the desktop's sound server.")
RIG_HELP = _(
    "Lets Pat key the radio and set its frequency. In Pat's configuration, add "
    "a rig with the address localhost:4532, then choose it, with PTT control, "
    "for ARDOP and VARA.")
TABLES_HELP = _(
    "On 1 January 2027, by their computer's clock, VARA HF and VARA FM stations "
    "switch to a new waveform. xara follows them, but needs VARA's own tables for "
    "it: Pat Desktop takes them from VARA's official installers, downloaded from "
    "Winlink's site, and keeps only the table files. Without them xara stays on "
    "the old waveform.")


def get_tables(parent, tables):
    """Ask to download VARA's installers again, or to choose them."""
    body = _("Pat Desktop downloads VARA's official installers from "
             "downloads.winlink.org, unpacks them without running them, and keeps "
             "only the tables xara needs.")
    if tables.error:
        body += "\n\n" + _("The last try failed: {}.").format(tables.error)
    body += "\n\n" + _("You can also choose installers you downloaded yourself: "
                        "VARA HF 4.9.1 and VARA FM 4.4.1, the .zip files or the .exe "
                        "inside them.")
    dialog = Adw.AlertDialog(heading=_("VARA's 2027 Tables"), body=body)
    dialog.add_response("cancel", _("_Not Now"))
    dialog.add_response("choose", _("_Choose Installers…"))
    dialog.add_response("download", _("_Download"))
    dialog.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("download")
    dialog.set_close_response("cancel")

    def response(_dialog, answer):
        if answer == "download":
            tables.download(by_user=True)
        elif answer == "choose":
            _choose_installers(parent, tables)
    dialog.connect("response", response)
    dialog.present(parent)


def _choose_installers(parent, tables):
    installers = Gtk.FileFilter(name=_("VARA installers"))
    for pattern in ("*.zip", "*.exe", "*.ZIP", "*.EXE"):
        installers.add_pattern(pattern)
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(installers)
    dialog = Gtk.FileDialog(title=_("Choose VARA Installers"), filters=filters)
    downloads = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
    if downloads:
        dialog.set_initial_folder(Gio.File.new_for_path(downloads))

    def done(dlg, result):
        try:
            files = dlg.open_multiple_finish(result)
        except GLib.Error:
            return
        paths = [f.get_path() for f in files if f.get_path()]
        tables.import_files(paths)
    root = parent.get_root() if isinstance(parent, Gtk.Widget) else parent
    dialog.open_multiple(root if isinstance(root, Gtk.Window) else None, None, done)


class Choice(Adw.ComboRow):
    """A combo row over (value, label) pairs; `on_change(value)` on selection."""

    def __init__(self, title, items, value, on_change, subtitle=None, search=False):
        super().__init__(title=title, subtitle=subtitle or "")
        self._on_change = None
        self.set_items(items, value)
        if search:
            self.set_enable_search(True)
            self.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self._on_change = on_change
        self.connect("notify::selected", self._changed)

    def set_items(self, items, value):
        items = list(items)
        if value not in [v for v, _l in items]:
            items.append((value, str(value)))
        self._values = [v for v, _l in items]
        handler, self._on_change = self._on_change, None
        self.set_model(Gtk.StringList.new([label for _v, label in items]))
        self.set_selected(self._values.index(value))
        self._on_change = handler

    @property
    def value(self):
        return self._values[self.get_selected()]

    def _changed(self, *_args):
        if self._on_change:
            self._on_change(self.value)


class ModemsDialog(Adw.PreferencesDialog):
    def __init__(self, manager, tables):
        super().__init__(title=_("Modems"), search_enabled=False, content_width=640)
        self.manager = manager
        self.tables = tables
        self._headers = {}
        self._rows = {}
        page = Adw.PreferencesPage()
        intro = Adw.PreferencesGroup(description=INTRO)
        page.add(intro)

        config = modems.read_pat_config()
        cards = modems.sound_cards()

        # Rig control.
        group = self._group("rigctld", _("Rig Control"), _("Hamlib rigctld"), RIG_HELP)
        opts = modems.settings("rigctld")
        models = [(n, f"{name} ({n})") for n, name in modems.rig_models()]
        group.add(Choice(_("Radio"), models, opts["model"],
                         lambda v: self._set("rigctld", model=v), search=True,
                         subtitle=_("“Hamlib Dummy” with RTS or DTR for PTT only")))
        group.add(self._device_row("rigctld", "device", _("Serial Port"),
                                   modems.serial_devices(), opts["device"]))
        group.add(Choice(_("Speed"), [(s, str(s) if s else _("Radio's default")) for s in SPEEDS],
                         opts["speed"], lambda v: self._set("rigctld", speed=v)))
        group.add(Choice(_("PTT"), [(p, RIGCTLD_PTT_LABELS[p]) for p in modems.RIGCTLD_PTT],
                         opts["ptt"], lambda v: self._set("rigctld", ptt=v)))
        page.add(group)

        # Modems.
        for service, subtitle in (
                ("ardop", "ardopcf"), ("varahf", None), ("varafm", "xara"),
                ("packet", "Direwolf")):
            title = modems.SERVICES[service][0]
            try:
                host, port = modems.service_address(service, config)
                where = _("Pat's {} address: {}:{}").format(title, host or "localhost", port)
            except modems.ConfigError as e:
                where = str(e)
            group = self._group(service, title, subtitle, where)
            opts = modems.settings(service)
            if service == "varahf":
                group.add(Choice(
                    _("Modem"),
                    [("xara", _("xara (VARA-compatible)")),
                     ("mercury", _("Mercury (talks to Mercury stations)"))],
                    opts["modem"], lambda v: self._modem_changed(v)))
            group.add(Choice(_("Sound Card"), cards, opts["sound"],
                             lambda v, s=service: self._set(s, sound=v)))
            if service == "varafm":
                group.add(Choice(_("Bandwidth"), [("wide", _("Wide")), ("narrow", _("Narrow"))],
                                 opts["width"], lambda v: self._set("varafm", width=v)))
            if service == "packet":
                group.add(Choice(_("Speed"), [(1200, "1200 bd (AFSK)"), (9600, "9600 bd (G3RUH)")],
                                 opts["baud"], lambda v: self._set("packet", baud=v)))
            ptt = Choice(_("PTT"), self._ptt_items(service), opts["ptt"],
                         lambda v, s=service: self._ptt_changed(s, v))
            group.add(ptt)
            device = self._device_row(service, "ptt_device", _("PTT Device"),
                                      self._ptt_devices(opts["ptt"]), opts["ptt_device"])
            group.add(device)
            self._rows[service] = (ptt, device)
            device.set_visible(opts["ptt"] in modems.PTT_NEEDS_DEVICE)
            page.add(group)
            if service == "varafm":
                page.add(self._tables_group())

        self.add(page)
        self._handler = manager.connect("changed", lambda _m, name: self._update_status(name))
        self._tables_handler = tables.connect("changed", lambda _t: self._update_tables())
        self.connect("closed", lambda _d: (manager.disconnect(self._handler),
                                           tables.disconnect(self._tables_handler)))
        self._update_tables()
        for name in modems.SERVICES:
            self._update_status(name)

    # Building -------------------------------------------------------------

    def _group(self, service, title, subtitle, description):
        group = Adw.PreferencesGroup(title=title, description=description)
        switch = Adw.SwitchRow(title=_("Run with Pat"),
                               subtitle=subtitle or "",
                               active=modems.settings(service)["enabled"])
        switch.connect("notify::active",
                       lambda row, _p: self._set(service, enabled=row.get_active()))
        status = Gtk.Label(css_classes=["dim-label", "caption"], wrap=True, xalign=1,
                           max_width_chars=28)
        group.set_header_suffix(status)
        group.add(switch)
        self._headers[service] = (status, switch)
        return group

    def _tables_group(self):
        group = Adw.PreferencesGroup(title=_("VARA 2027 Waveform"), description=TABLES_HELP)
        self._tables_button = Gtk.Button(label=_("Get Tables…"), valign=Gtk.Align.CENTER)
        self._tables_button.add_css_class("flat")
        self._tables_button.connect("clicked", lambda _b: get_tables(self, self.tables))
        group.set_header_suffix(self._tables_button)
        self._table_rows = {}
        for band in varatables.TABLES:
            row = Adw.ActionRow(title=_("{} tables").format(varatables.NAMES[band]))
            group.add(row)
            self._table_rows[band] = row
        return group

    def _update_tables(self):
        for band, row in self._table_rows.items():
            if varatables.ready(band):
                text = _("Installed")
            elif self.tables.working:
                text = _("Getting them…")
            elif self.tables.error:
                text = _("Missing: {}").format(self.tables.error)
            elif varatables.after_switch():
                text = _("Missing: xara is on the old waveform VARA no longer uses")
            else:
                text = _("Missing: needed from 1 January 2027")
            row.set_subtitle(text)
        self._tables_button.set_sensitive(not self.tables.working)
        self._tables_button.set_visible(bool(self.tables.missing()) or self.tables.working)

    def _device_row(self, service, key, title, devices, value):
        items = [("", _("None"))] + [(d, d.rsplit("/", 1)[-1]) for d in devices]
        return Choice(title, items, value, lambda v: self._set(service, **{key: v}))

    def _ptt_modem(self, service):
        if service == "varahf":
            return modems.settings("varahf")["modem"]
        return {"ardop": "ardopcf", "varafm": "xara", "packet": "direwolf"}[service]

    def _ptt_items(self, service):
        modem = self._ptt_modem(service)
        # Pat has no PTT for packet: there "none" is the radio's VOX.
        labels = {**modems.PTT_LABELS, "none": _("VOX")} if modem == "direwolf" else modems.PTT_LABELS
        return [(p, labels[p]) for p in modems.MODEM_PTT[modem]]

    @staticmethod
    def _ptt_devices(ptt):
        return modems.hidraw_devices() if ptt == "cm108" else modems.serial_devices()

    # Changes --------------------------------------------------------------

    def _set(self, service, **values):
        modems.save_settings(service, values)
        self.manager.schedule_apply(service)

    def _ptt_changed(self, service, ptt):
        _ptt_row, device = self._rows[service]
        current = modems.settings(service)["ptt_device"]
        device.set_items([("", _("None"))] + [(d, d.rsplit("/", 1)[-1])
                                             for d in self._ptt_devices(ptt)], current)
        device.set_visible(ptt in modems.PTT_NEEDS_DEVICE)
        self._set(service, ptt=ptt)

    def _modem_changed(self, modem):
        ptt_row, _device = self._rows["varahf"]
        allowed = modems.MODEM_PTT[modem]
        ptt = modems.settings("varahf")["ptt"]
        if ptt not in allowed:
            ptt = "none"
        modems.save_settings("varahf", {"modem": modem, "ptt": ptt})
        ptt_row.set_items(self._ptt_items("varahf"), ptt)
        self._ptt_changed("varahf", ptt)

    def _update_status(self, name):
        if name not in self._headers:
            return
        label, _switch = self._headers[name]
        service = self.manager.services[name]
        text = {"running": _("Running"), "stopped": ""}.get(service.status, service.message)
        label.set_label(text)
        label.set_tooltip_text(service.message or None)
        if service.status == "failed":
            label.add_css_class("error")
        else:
            label.remove_css_class("error")


def present(parent, manager, tables):
    dialog = ModemsDialog(manager, tables)
    dialog.present(parent)
    return dialog

