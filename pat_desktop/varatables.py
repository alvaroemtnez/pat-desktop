# SPDX-License-Identifier: GPL-3.0-or-later
"""VARA's 2027 waveform tables, for xara.

From 2027 (by the computer's local clock) VARA HF 4.9.1 and VARA FM 4.4.1
switch to a new waveform. Its tables cannot be generated: xara reads them
from files that ship with VARA. Those files are VARA's, so Pat Desktop does
not include them. Instead it downloads the official installers from Winlink's
download site, unpacks them with the bundled innoextract (no Windows code
runs), keeps only the table files, checks them against the known checksums
and stores them in its data folder. If the download fails, the user can pick
installers downloaded by hand (.zip or .exe).

Without the tables xara stays on the old waveform, which VARA stations stop
using in 2027.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from gettext import gettext as _

from gi.repository import GLib, GObject

from . import VERSION

SWITCH_YEAR = 2027

# The files xara needs, by checksum. They are the same in every installer
# build of these versions seen so far.
TABLES = {
    "hf": {
        "Binary1.dat": "2a6778f7b7c87907c3f7237289423b66cfe88c64464667b15a3338278bbcec55",
        "Binary2.dat": "f367d7e5addfe8da3385d383998afc5f5bb1a43cc17589941fc11ddd1d0afd26",
        "Binary3.dat": "f72b321587f47142cdd45b605cf3de64f5aa961c52193fe22b520dc5ab3ac260",
        "Mod1.dat": "4e69cd7aebb0db45984409717d1d67dfc9257526fa6309bc86ad3dfaf40f4452",
        "Mod2.dat": "0887fa3e0deba8c5e65d2dcb6cc79f7fe9e8e213ceb4716e375e557068e8ad79",
    },
    "fm": {
        "Binary1.dat": "e1401d2362282dc0503a17f1517101b4ca150db8bf61a083ecb2eca7f70e2096",
        "Binary2.dat": "b2c2f496b636c764ba6b18c44f50a4cf20723b2d3daf0b97a78923410a45a3a3",
    },
}
NAMES = {"hf": _("VARA HF"), "fm": _("VARA FM")}

# The official installers (VARA's own site links here).
DOWNLOADS = {
    "hf": "https://downloads.winlink.org/VARA%20Products/VARA%20HF%20v4.9.1%20%20setup.zip",
    "fm": "https://downloads.winlink.org/VARA%20Products/VARA%20FM%20v4.4.1%20%20setup.zip",
}
# Winlink's CDN turns away clients that send no user agent of their own.
USER_AGENT = f"PatDesktop/{VERSION} (+https://code.alvaroedo.io/alvaroemtnez/pat-desktop)"
DOWNLOAD_TIMEOUT_S = 60
MAX_DOWNLOAD = 64 << 20  # the installers are 6 and 11 MB
MAX_INSTALLER = 128 << 20
INNOEXTRACT_TIMEOUT_S = 120

_valid = {}  # mode: bool, until the next install


def tables_dir(mode):
    return os.path.join(GLib.get_user_data_dir(), "pat-desktop", "xara", f"keying-{mode}")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ready(mode):
    """The tables for `mode` ("hf" or "fm") are installed and intact."""
    if mode not in _valid:
        directory = tables_dir(mode)
        try:
            _valid[mode] = all(_sha256(os.path.join(directory, name)) == digest
                               for name, digest in TABLES[mode].items())
        except OSError:
            _valid[mode] = False
    return _valid[mode]


def keying_dir(mode):
    """The directory to give xara for `mode`, or None without the tables."""
    return tables_dir(mode) if ready(mode) else None


def after_switch():
    return time.localtime().tm_year >= SWITCH_YEAR


class TablesError(Exception):
    pass


# Work, in a thread ----------------------------------------------------------

def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as resp, \
                open(dest, "wb") as out:
            size = 0
            for chunk in iter(lambda: resp.read(1 << 16), b""):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise TablesError(_("the download is far bigger than VARA's installer"))
                out.write(chunk)
    except urllib.error.HTTPError as e:
        raise TablesError(_("the download site answered {} {}").format(e.code, e.reason))
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", None) or e
        raise TablesError(_("could not download it ({})").format(reason))


def _installers(path, work):
    """The installer executables in `path`: itself, or the .exe files in a zip."""
    if not zipfile.is_zipfile(path):
        return [path]
    found = []
    with zipfile.ZipFile(path) as z:
        for i, info in enumerate(z.infolist()):
            if info.is_dir() or not info.filename.lower().endswith(".exe"):
                continue
            if info.file_size > MAX_INSTALLER:
                raise TablesError(_("{} is too big to be VARA's installer").format(info.filename))
            dest = os.path.join(work, f"installer-{i}.exe")
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            found.append(dest)
    if not found:
        raise TablesError(_("the zip file has no installer in it"))
    return found


def _unpack(installer, dest):
    from .modems import find_binary  # modems imports this module
    binary = find_binary("innoextract")
    if not binary:
        raise TablesError(_("innoextract is not part of this build"))
    try:
        proc = subprocess.run([binary, "--silent", "--output-dir", dest, installer],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=INNOEXTRACT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TablesError(_("could not unpack it ({})").format(e))
    if proc.returncode != 0:
        last = (proc.stderr.strip().splitlines() or [""])[-1]
        raise TablesError(_("it is not an installer innoextract can read ({})").format(last))


def _tables_in(tree):
    """{mode: {name: path}} of the complete, intact table sets under `tree`."""
    by_digest = {}
    for root, _dirs, files in os.walk(tree):
        for name in files:
            if name.endswith(".dat"):
                path = os.path.join(root, name)
                by_digest[(name, _sha256(path))] = path
    found = {}
    for mode, tables in TABLES.items():
        paths = {name: by_digest.get((name, digest)) for name, digest in tables.items()}
        if all(paths.values()):
            found[mode] = paths
    return found


def _install(mode, paths):
    final = tables_dir(mode)
    parent = os.path.dirname(final)
    os.makedirs(parent, exist_ok=True)
    new = tempfile.mkdtemp(prefix=f".keying-{mode}-", dir=parent)
    for name, path in paths.items():
        shutil.copyfile(path, os.path.join(new, name))
    old = None
    if os.path.exists(final):
        old = tempfile.mkdtemp(prefix=f".keying-{mode}-old-", dir=parent)
        os.rename(final, os.path.join(old, "keying"))
    os.rename(new, final)
    if old:
        shutil.rmtree(old, ignore_errors=True)
    _valid.pop(mode, None)


def _from_installers(paths, wanted):
    """Install the tables of `wanted` modes found in the installers `paths`.

    Returns the modes installed."""
    cache = os.path.join(GLib.get_user_cache_dir(), "pat-desktop")
    os.makedirs(cache, exist_ok=True)
    installed = set()
    errors = []
    with tempfile.TemporaryDirectory(prefix="vara-", dir=cache) as work:
        for n, path in enumerate(paths):
            # One unreadable file among several is skipped, not fatal.
            try:
                for m, installer in enumerate(_installers(path, work)):
                    out = os.path.join(work, f"out-{n}-{m}")
                    _unpack(installer, out)
                    for mode, tables in _tables_in(out).items():
                        if mode in wanted and mode not in installed:
                            _install(mode, tables)
                            installed.add(mode)
                    shutil.rmtree(out, ignore_errors=True)
            except TablesError as e:
                errors.append(f"{os.path.basename(path)}: {e}" if len(paths) > 1 else str(e))
    if errors and not installed:
        raise TablesError("; ".join(errors))
    return installed


def _download_and_install(mode):
    cache = os.path.join(GLib.get_user_cache_dir(), "pat-desktop")
    os.makedirs(cache, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vara-", dir=cache) as work:
        archive = os.path.join(work, "setup.zip")
        _download(DOWNLOADS[mode], archive)
        if mode not in _from_installers([archive], {mode}):
            raise TablesError(_("the installer does not have the tables this xara knows "
                                "(a newer VARA?)"))


# The service the app uses -----------------------------------------------------

class VaraTables(GObject.Object):
    """Fetches and installs the tables in the background.

    "changed" is emitted whenever ready(), `working` or `error` changes."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, log):
        super().__init__()
        self._log = log
        self.working = False
        self.error = ""  # why the last attempt failed, for the user
        self.by_user = False  # the last attempt was asked for, not automatic

    @staticmethod
    def missing():
        return [mode for mode in TABLES if not ready(mode)]

    def download(self, by_user=False):
        """Download the official installers of the missing tables."""
        missing = self.missing()
        if self.working or not missing:
            return
        self._run(lambda: self._download_all(missing), by_user)

    def import_files(self, paths):
        """Take the tables from installers the user chose (.zip or .exe)."""
        if self.working or not paths:
            return
        self._run(lambda: self._import(paths), True)

    def _download_all(self, modes):
        errors = []
        for mode in modes:
            self._log_idle(f"[pat-desktop] Downloading the {NAMES[mode]} installer for "
                           f"VARA's 2027 tables: {DOWNLOADS[mode]}")
            try:
                _download_and_install(mode)
                self._log_idle(f"[pat-desktop] {NAMES[mode]} 2027 tables installed.")
            except (TablesError, OSError) as e:
                errors.append(f"{NAMES[mode]}: {e}")
        return "; ".join(errors)

    def _import(self, paths):
        wanted = set(TABLES)
        try:
            installed = _from_installers(paths, wanted)
        except (TablesError, OSError) as e:
            return str(e)
        for mode in sorted(installed):
            self._log_idle(f"[pat-desktop] {NAMES[mode]} 2027 tables installed from "
                           f"the chosen installer.")
        if not installed:
            return _("none of the chosen files is a VARA HF 4.9.1 or VARA FM 4.4.1 installer")
        return ""

    def _run(self, job, by_user):
        self.working = True
        self.by_user = by_user
        self.error = ""
        self.emit("changed")

        def worker():
            try:
                error = job()
            except Exception as e:  # never leave `working` stuck
                error = str(e)
            GLib.idle_add(self._done, error)
        threading.Thread(target=worker, daemon=True).start()

    def _done(self, error):
        _valid.clear()  # a check may have raced with an install
        self.working = False
        self.error = error
        if error:
            self._log(f"[pat-desktop] VARA's 2027 tables: {error}")
        self.emit("changed")
        return GLib.SOURCE_REMOVE

    def _log_idle(self, line):
        GLib.idle_add(lambda: (self._log(line), GLib.SOURCE_REMOVE)[1])
