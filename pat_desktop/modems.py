# SPDX-License-Identifier: GPL-3.0-or-later
"""The bundled modems and rigctld, run alongside Pat.

Pat talks to modems over TCP, at the addresses in its own configuration
(ARDOP, VARA HF, VARA FM, AGWPE for packet). Each service here provides one
of those transports with a bundled modem, listening on the address Pat is
configured to use, so Pat's configuration stays the single place for them.
Settings that Pat has no place for (sound card, PTT, which modem) are Pat
Desktop's own and live in its state file.

  service  Pat setting      modem
  ardop    ardop.addr       ardopcf
  varahf   varahf.addr      xara or Mercury
  varafm   varafm.addr      xara (FM)
  packet   agwpe.addr       Direwolf
  rigctld  (a hamlib rig)   Hamlib's rigctld, on 127.0.0.1:4532

Pat keys the radio itself through a rig when "ptt_ctrl" is on for ARDOP and
VARA; with the PTT setting "none" the modem leaves the radio alone (Pat or
VOX keys it).
"""

import json
import os
import re
import shutil
import signal
from gettext import gettext as _

from gi.repository import Gio, GLib, GObject

from . import state

RIGCTLD_ADDR = ("127.0.0.1", 4532)
STOP_KILL_MS = 3000
# rigctld first: the modems that key through it connect to it when they start.
RIGCTLD_HEADSTART_MS = 1500
LOCAL_HOSTS = ("", "localhost", "127.0.0.1", "::1", "[::1]")

# PTT methods, and which service and modem supports each. "none" leaves the
# radio to Pat (rig control with PTT) or to VOX.
PTT_LABELS = {
    "none": _("Pat or VOX"),
    "rigctld": _("Rig control (rigctld)"),
    "rts": _("Serial RTS"),
    "dtr": _("Serial DTR"),
    "cm108": _("CM108 sound card GPIO"),
}
PTT_NEEDS_DEVICE = {"rts", "dtr", "cm108"}
MODEM_PTT = {
    "ardopcf": ["none", "rts"],
    "xara": ["none", "rigctld", "rts", "dtr", "cm108"],
    "mercury": ["none", "rigctld", "rts", "cm108"],
    "direwolf": ["none", "rigctld", "rts", "dtr", "cm108"],
}
RIGCTLD_PTT = ["cat", "rts", "dtr", "none"]

SERVICES = {
    # service: (title, Pat config section, default address)
    "ardop": (_("ARDOP"), "ardop", "localhost:8515"),
    "varahf": (_("VARA HF"), "varahf", "localhost:8300"),
    "varafm": (_("VARA FM"), "varafm", "localhost:8300"),
    "packet": (_("Packet"), "agwpe", "localhost:8000"),
    "rigctld": (_("Rig Control"), None, None),
}

DEFAULTS = {
    "ardop": {"enabled": False, "sound": "default", "ptt": "none", "ptt_device": ""},
    "varahf": {"enabled": False, "modem": "xara", "sound": "default", "ptt": "none",
               "ptt_device": ""},
    "varafm": {"enabled": False, "sound": "default", "width": "wide", "ptt": "none",
               "ptt_device": ""},
    "packet": {"enabled": False, "sound": "default", "baud": 1200, "ptt": "none",
               "ptt_device": ""},
    "rigctld": {"enabled": False, "model": 1, "device": "", "speed": 0, "ptt": "cat"},
}


class ConfigError(Exception):
    """A service cannot run with the current settings; the message says why."""


def find_binary(name):
    for directory in (os.environ.get("PAT_DESKTOP_MODEM_DIR"), "/app/bin",
                      os.path.dirname(os.path.realpath(__file__)) + "/../../../bin"):
        if directory:
            path = os.path.normpath(os.path.join(directory, name))
            if os.access(path, os.X_OK):
                return path
    return shutil.which(name)


def spawn(argv, flags):
    """Gio.Subprocess for a bundled binary, which finds the bundled libraries
    (Hamlib) in ../lib next to it: the AppImage has no rpath for them."""
    launcher = Gio.SubprocessLauncher.new(flags)
    libdir = os.path.normpath(os.path.join(os.path.dirname(argv[0]), "..", "lib"))
    if os.path.isdir(libdir):
        current = os.environ.get("LD_LIBRARY_PATH")
        launcher.setenv("LD_LIBRARY_PATH", libdir + (":" + current if current else ""), True)
    return launcher.spawnv(argv)


def settings(service):
    saved = state.get("modems", {}).get(service, {})
    return {**DEFAULTS[service], **saved}


def save_settings(service, values):
    modems = dict(state.get("modems", {}))
    modems[service] = {**settings(service), **values}
    state.set("modems", modems)


def pat_config_path():
    return os.path.join(GLib.get_user_config_dir(), "pat", "config.json")


def read_pat_config():
    try:
        with open(pat_config_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def service_address(service, config):
    """(host, port) Pat expects the service at."""
    _title, section, default = SERVICES[service]
    addr = (config.get(section) or {}).get("addr") or default
    host, _sep, port = addr.rpartition(":")
    try:
        return host, int(port)
    except ValueError:
        raise ConfigError(_("Pat's address for it, “{}”, has no port.").format(addr))


# Sound cards and devices -------------------------------------------------

def sound_cards():
    """[(device, label)]: the system default, then each ALSA card."""
    cards = [("default", _("System default"))]
    try:
        with open("/proc/asound/cards") as f:
            lines = f.read().splitlines()
    except OSError:
        return cards
    for line in lines:
        # " 1 [Device         ]: USB-Audio - USB Audio Device"
        if "[" not in line or "]:" not in line:
            continue
        card_id = line.split("[", 1)[1].split("]", 1)[0].strip()
        name = line.split("]:", 1)[1].split(" - ", 1)[-1].strip()
        # The id tells apart cards of the same model.
        label = f"{name} ({card_id})" if name and name != card_id else card_id
        cards.append((f"plughw:CARD={card_id},DEV=0", label))
    return cards


def serial_devices():
    """Serial ports, by their stable /dev/serial/by-id names where there are any."""
    found = []
    by_id = "/dev/serial/by-id"
    try:
        found += sorted(os.path.join(by_id, n) for n in os.listdir(by_id))
    except OSError:
        pass
    linked = {os.path.realpath(p) for p in found}
    try:
        for name in sorted(os.listdir("/dev")):
            path = "/dev/" + name
            if name.startswith(("ttyUSB", "ttyACM")) and path not in linked:
                found.append(path)
    except OSError:
        pass
    return found


def hidraw_devices():
    try:
        return sorted("/dev/" + n for n in os.listdir("/dev") if n.startswith("hidraw"))
    except OSError:
        return []


def rig_models(binary=None):
    """[(model number, "Maker Model")] from `rigctld -l`."""
    binary = binary or find_binary("rigctld")
    if not binary:
        return [(1, "Hamlib Dummy")]
    try:
        proc = spawn([binary, "-l"], Gio.SubprocessFlags.STDOUT_PIPE
                     | Gio.SubprocessFlags.STDERR_SILENCE)
        _ok, out, _err = proc.communicate_utf8(None, None)
    except GLib.Error:
        return [(1, "Hamlib Dummy")]
    models = []
    for line in (out or "").splitlines():
        # " Rig #  Mfg                    Model                   Version         Status      Macro"
        cols = re.split(r"\s{2,}", line.strip())
        if len(cols) >= 3 and cols[0].isdigit():
            models.append((int(cols[0]), f"{cols[1]} {cols[2]}"))
    return models or [(1, "Hamlib Dummy")]


# Command lines --------------------------------------------------------------

def _need_device(opts):
    if opts["ptt"] in PTT_NEEDS_DEVICE and not opts["ptt_device"]:
        if opts["ptt"] == "cm108":
            return None  # Direwolf and Mercury find the CM108 themselves
        raise ConfigError(_("Choose the device for PTT."))
    return opts["ptt_device"]


def _callsign(config):
    call = (config.get("mycall") or "").strip()
    if not call:
        raise ConfigError(_("Set your callsign in Pat's configuration first."))
    return call


def _xara(binary, call, opts, port, mode):
    if opts["sound"] == "default":
        # xara refuses to transmit into whatever the default device is.
        raise ConfigError(_("xara needs the radio's own sound card, not the system default."))
    argv = [binary, "--call", call, *mode, "--audio", "alsa",
            "--capture", opts["sound"], "--playback", opts["sound"],
            "--addr", "127.0.0.1", "--port", str(port), "--kiss-port", "off",
            "--registered", "--radio"]
    device = _need_device(opts)
    ptt = opts["ptt"]
    if ptt == "none":
        argv += ["--ptt", "vox"]  # xara does not key; Pat or VOX does
    elif ptt == "rigctld":
        argv += ["--ptt", "rigctld:%s:%d" % RIGCTLD_ADDR]
    elif ptt == "cm108" and not device:
        raise ConfigError(_("Choose the CM108 device (hidraw) for PTT."))
    else:
        argv += ["--ptt", f"{ptt}:{device}"]
    return argv


def command(service, config, workdir):
    """argv for `service`, or raise ConfigError."""
    opts = settings(service)
    if service == "rigctld":
        binary = find_binary("rigctld")
        if not binary:
            raise ConfigError(_("rigctld is not part of this build."))
        argv = [binary, "-m", str(opts["model"]), "-T", RIGCTLD_ADDR[0],
                "-t", str(RIGCTLD_ADDR[1])]
        if opts["model"] != 1 or opts["ptt"] in ("rts", "dtr"):
            if not opts["device"]:
                raise ConfigError(_("Choose the radio's serial port."))
            argv += ["-r", opts["device"]]
        if opts["speed"]:
            argv += ["-s", str(opts["speed"])]
        if opts["ptt"] in ("rts", "dtr", "none"):
            argv += ["-P", opts["ptt"].upper()]
        return argv

    host, port = service_address(service, config)
    if host.lower() not in LOCAL_HOSTS:
        raise ConfigError(_("Pat expects it at {}, not on this computer.").format(host))
    modem = {"ardop": "ardopcf", "varafm": "xara", "packet": "direwolf"}.get(
        service, opts.get("modem", "xara"))
    binary = find_binary(modem)
    if not binary:
        raise ConfigError(_("{} is not part of this build.").format(modem))
    if opts["ptt"] not in MODEM_PTT[modem]:
        raise ConfigError(_("{} cannot key the radio with {}.").format(
            modem, PTT_LABELS.get(opts["ptt"], opts["ptt"])))

    if modem == "ardopcf":
        argv = [binary, "--nologfile"]
        if opts["ptt"] == "rts":
            argv += ["--ptt", _need_device(opts)]
        return argv + [str(port), opts["sound"], opts["sound"]]

    if modem == "xara" and service == "varahf":
        width = str((config.get("varahf") or {}).get("bandwidth") or 2300)
        return _xara(binary, _callsign(config), opts, port, ["--hf", width])
    if modem == "xara":
        return _xara(binary, _callsign(config), opts, port, ["--fm", opts["width"]])

    if modem == "mercury":
        argv = [binary, "-x", "alsa", "-i", opts["sound"], "-o", opts["sound"],
                "-p", str(port)]
        device = _need_device(opts)
        if opts["ptt"] == "rigctld":
            argv += ["-R", "2", "-A", "%s:%d" % RIGCTLD_ADDR]
        elif opts["ptt"] == "rts":
            argv += ["-P", "serial", "-A", device]
        elif opts["ptt"] == "cm108":
            argv += ["-P", "cm108"]
        return argv

    # Direwolf reads a configuration file, written for each start.
    call = _callsign(config)
    device = _need_device(opts)
    ptt = {
        "none": None,
        "rigctld": "PTT RIG 2 %s:%d" % RIGCTLD_ADDR,
        "rts": f"PTT {device} RTS",
        "dtr": f"PTT {device} DTR",
        "cm108": f"PTT CM108 {device}" if device else "PTT CM108",
    }[opts["ptt"]]
    lines = [
        "# Written by Pat Desktop for each start; edits are lost.",
        f"ADEVICE {opts['sound']} {opts['sound']}",
        "ACHANNELS 1",
        "CHANNEL 0",
        f"MYCALL {call}",
        f"MODEM {int(opts['baud'])}",
        *([ptt] if ptt else []),
        f"AGWPORT {port}",
        "KISSPORT 0",
    ]
    conf = os.path.join(workdir, "direwolf.conf")
    with open(conf, "w") as f:
        f.write("\n".join(lines) + "\n")
    return [binary, "-c", conf, "-t", "0"]


# Processes ----------------------------------------------------------------

class Service(GObject.Object):
    """One supervised process. status: stopped, running, failed (with message)."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, name, log):
        super().__init__()
        self.name = name
        self.status = "stopped"
        self.message = ""
        self.argv = None
        self._log = log
        self._proc = None
        self._kill_id = 0
        self._then = None
        self._stopping = False
        self._last_line = ""

    @property
    def running(self):
        return self._proc is not None

    def start(self, argv):
        if self._proc:
            return
        self.argv = argv
        self._last_line = ""
        label = os.path.basename(argv[0])
        self._log(f"[pat-desktop] Starting {label}: {' '.join(argv)}")
        try:
            self._proc = spawn(argv, Gio.SubprocessFlags.STDOUT_PIPE
                               | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            self._set("failed", _("Could not start {}: {}").format(label, e.message))
            return
        pids = dict(state.get("modem_pids", {}))
        pids[self.name] = int(self._proc.get_identifier())
        state.set("modem_pids", pids)
        stream = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, (self._proc, label))
        self._proc.wait_async(None, self._on_exit, label)
        self._set("running", "")

    def stop(self, then=None):
        """Stop the process (SIGTERM, then SIGKILL); `then` runs once it is gone."""
        if not self._proc:
            if self.status == "running":
                self._set("stopped", "")
            if then:
                then()
            return
        self._then = then
        self._stopping = True
        self._proc.send_signal(signal.SIGTERM)
        proc = self._proc
        self._kill_id = GLib.timeout_add(STOP_KILL_MS, lambda: (
            proc.force_exit() if proc is self._proc else None, False)[1])

    def fail(self, message):
        """Not started: the settings or Pat's configuration need attention."""
        self.argv = None
        self._set("failed", message)

    def _set(self, status, message):
        self.status, self.message = status, message
        if message:
            self._log(f"[pat-desktop] {self.name}: {message}")
        self.emit("changed")

    def _on_line(self, stream, result, data):
        proc, label = data
        try:
            line, _len = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:
            return
        self._log(f"[{label}] {line}")
        if line.strip():
            self._last_line = line.strip()
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, data)

    def _on_exit(self, proc, result, label):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        if proc is not self._proc:
            return
        self._proc = None
        if self._kill_id:
            GLib.source_remove(self._kill_id)
            self._kill_id = 0
        pids = dict(state.get("modem_pids", {}))
        pids.pop(self.name, None)
        state.set("modem_pids", pids)
        then, self._then = self._then, None
        if self._stopping:
            self._stopping = False
            self._log(f"[pat-desktop] {label} stopped.")
            self._set("stopped", "")
            if then:
                then()
        else:
            # Its last words usually say why (a busy sound card, a bad option).
            reason = self._last_line or _("status {}").format(
                proc.get_exit_status() if proc.get_if_exited() else -1)
            self._set("failed", _("{} stopped: {}").format(label, reason))


def _reap_orphans():
    """Stop modems a crashed Pat Desktop left behind (outside Flatpak)."""
    names = {"rigctld", "ardopcf", "xara", "mercury", "direwolf"}
    for pid in state.get("modem_pids", {}).values():
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                exe = os.path.basename(f.read().split(b"\0")[0]).decode()
        except (OSError, IndexError, UnicodeDecodeError):
            continue
        if exe in names:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    state.set("modem_pids", {})


class ModemManager(GObject.Object):
    """Runs the enabled services, and restarts them when their settings or
    Pat's configuration change."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, log):
        super().__init__()
        self.services = {name: Service(name, log) for name in SERVICES}
        for name, service in self.services.items():
            service.connect("changed", lambda _s, n=name: self.emit("changed", n))
        self._log = log
        self._active = False
        self._pending = {}
        self._monitor = None
        self.workdir = os.path.join(GLib.get_user_data_dir(), "pat-desktop", "modems")

    def start(self):
        """Start the enabled services (rigctld first) and follow changes.

        Called each time Pat is up; after the first, it only re-checks."""
        if self._active:
            self.refresh()
            return
        _reap_orphans()
        os.makedirs(self.workdir, exist_ok=True)
        self._active = True
        if not self._monitor:
            self._monitor = Gio.File.new_for_path(pat_config_path()).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None)
            self._monitor.set_rate_limit(1000)
            self._monitor.connect("changed", lambda *_: self.refresh())
        self.apply("rigctld")
        delay = RIGCTLD_HEADSTART_MS if self.services["rigctld"].running else 0
        GLib.timeout_add(delay, lambda: (self.refresh(), False)[1])

    def stop_all(self, then=None):
        self._active = False
        running = [s for s in self.services.values() if s.running]
        if not running:
            if then:
                then()
            return
        left = [len(running)]

        def one_done():
            left[0] -= 1
            if left[0] == 0 and then:
                then()
        for service in running:
            service.stop(one_done)

    def stop_all_sync(self, timeout_ms=STOP_KILL_MS + 1000):
        done = []
        self.stop_all(lambda: done.append(True))
        ctx = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + timeout_ms * 1000
        while not done and GLib.get_monotonic_time() < deadline:
            ctx.iteration(True)

    def refresh(self):
        """Re-check every service against the settings and Pat's configuration."""
        for name in SERVICES:
            self.apply(name)

    def apply(self, name):
        """Start, stop or restart `name` to match its settings."""
        service = self.services[name]
        if not self._active:
            return
        if not settings(name)["enabled"]:
            if service.running:
                service.stop()
            elif service.status != "stopped":
                service.status, service.message = "stopped", ""
                service.emit("changed")
            return
        try:
            argv = command(name, read_pat_config(), self.workdir)
            self._check_port_clash(name)
        except ConfigError as e:
            if service.running:
                service.stop(lambda: service.fail(str(e)))
            else:
                service.fail(str(e))
            return
        if service.running and service.argv == argv:
            return
        if service.running:
            service.stop(lambda: self._active and service.start(argv))
        else:
            service.start(argv)

    def schedule_apply(self, name, delay_ms=600):
        """apply() after the settings stop changing (typing, toggling)."""
        if name in self._pending:
            GLib.source_remove(self._pending[name])

        def run():
            del self._pending[name]
            self.apply(name)
            if name == "rigctld":
                self.refresh()  # modems keying through rigctld reconnect
            return GLib.SOURCE_REMOVE
        self._pending[name] = GLib.timeout_add(delay_ms, run)

    def _check_port_clash(self, name):
        if name == "rigctld":
            return
        # Of two enabled services on one port, the one listed first runs.
        config = read_pat_config()
        _host, port = service_address(name, config)
        for other in list(SERVICES)[:list(SERVICES).index(name)]:
            if other == "rigctld" or not settings(other)["enabled"]:
                continue
            try:
                other_port = service_address(other, config)[1]
            except ConfigError:
                continue
            if other_port == port:
                raise ConfigError(_(
                    "{} uses the same port ({}) in Pat's configuration. Change one "
                    "of the two addresses there.").format(SERVICES[other][0], port))
