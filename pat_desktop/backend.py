# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the unmodified upstream `pat` binary as a child process."""

import json
import os
import random
import shutil
import signal
import socket
import time
import urllib.request
from collections import deque

from gi.repository import Gio, GLib, GObject

from . import state

HOST = "127.0.0.1"
LOG_LINES = 5000
READY_TIMEOUT_MS = 20000
# Pat traps only SIGINT/SIGHUP. The first SIGINT aborts an active connection
# instead of quitting, so a second one may be needed before falling back to
# SIGKILL.
SIGINT_RETRY_MS = 2000
KILL_AFTER_MS = 10000


def find_pat_binary():
    override = os.environ.get("PAT_DESKTOP_PAT_BINARY")
    if override:
        return override
    if os.path.exists("/app/bin/pat"):
        return "/app/bin/pat"
    return shutil.which("pat")


def pat_version(binary):
    try:
        proc = Gio.Subprocess.new([binary, "version"], Gio.SubprocessFlags.STDOUT_PIPE
                                  | Gio.SubprocessFlags.STDERR_SILENCE)
        _, out, _ = proc.communicate_utf8(None, None)
        return out.strip() or None
    except GLib.Error:
        return None


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Go listeners set SO_REUSEADDR, so lingering TIME_WAIT sockets from
        # the previous run do not make the port unusable for Pat.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def _pick_port():
    # A stable port keeps the web UI's origin (and so its localStorage) the
    # same between launches.
    port = state.get("port")
    if isinstance(port, int) and _port_free(port):
        return port
    for _ in range(50):
        port = random.randint(49152, 65000)
        if _port_free(port):
            state.set("port", port)
            return port
    raise RuntimeError("no free local port found")


def _reap_orphan():
    """Stop a Pat left behind by a previous wrapper that crashed.

    Only matters outside Flatpak: inside the sandbox the PID namespace, and
    every process in it, dies with the wrapper.
    """
    pid = state.get("pid")
    if not isinstance(pid, int):
        return
    state.set("pid", None)
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().split(b"\0")
    except OSError:
        return
    # Guard against PID reuse: only touch a process that looks like ours.
    if not (cmdline and os.path.basename(cmdline[0]) == b"pat"
            and b"http" in cmdline and b"--addr" in cmdline):
        return
    for sig in (signal.SIGINT, signal.SIGINT, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        for _ in range(20):
            time.sleep(0.1)
            if not os.path.exists(f"/proc/{pid}"):
                return


class PatBackend(GObject.Object):
    """States: stopped -> starting -> running -> stopping -> stopped."""

    __gsignals__ = {
        "ready": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "failed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "log-line": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self.binary = find_pat_binary()
        self.port = None
        self.state = "stopped"
        self.log = deque(maxlen=LOG_LINES)
        self._proc = None
        self._poll_id = 0
        self._stop_ids = []
        self._on_stopped = None

    @property
    def base_url(self):
        return f"http://{HOST}:{self.port}"

    def start(self):
        if self.state in ("starting", "running"):
            return
        if not self.binary:
            self._fail("The pat binary was not found. Set PAT_DESKTOP_PAT_BINARY "
                       "or install Pat.")
            return
        _reap_orphan()
        try:
            self.port = _pick_port()
        except RuntimeError as e:
            self._fail(str(e))
            return

        argv = [self.binary, "http", "--addr", f"{HOST}:{self.port}"]
        self._append_log(f"[pat-desktop] Starting: {' '.join(argv)}")
        try:
            self._proc = Gio.Subprocess.new(
                argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            self._fail(f"Could not start Pat: {e.message}")
            return

        self.state = "starting"
        state.set("pid", int(self._proc.get_identifier()))
        stream = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, self._proc)
        self._proc.wait_async(None, self._on_exit, self._proc)
        started = GLib.get_monotonic_time()
        self._poll_id = GLib.timeout_add(100, self._poll_ready, started)

    def stop(self, on_stopped=None):
        """Ask Pat to shut down gracefully; escalate if it does not."""
        self._on_stopped = on_stopped
        if not self._proc or self.state == "stopped":
            self.state = "stopped"
            self._notify_stopped()
            return
        if self.state == "stopping":
            return
        self.state = "stopping"
        self._cancel_poll()
        proc = self._proc
        proc.send_signal(signal.SIGINT)
        self._stop_ids = [
            GLib.timeout_add(SIGINT_RETRY_MS, self._signal_once, proc, signal.SIGINT),
            GLib.timeout_add(KILL_AFTER_MS, self._signal_once, proc, signal.SIGKILL),
        ]

    def stop_sync(self, timeout_ms=KILL_AFTER_MS):
        """Blocking variant for application shutdown."""
        done = []
        self.stop(lambda: done.append(True))
        ctx = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + timeout_ms * 1000 + 2_000_000
        while not done and GLib.get_monotonic_time() < deadline:
            ctx.iteration(True)

    def restart(self):
        self.stop(self.start)

    def status(self):
        """Pat's /api/status, or None if unreachable."""
        if self.state != "running":
            return None
        try:
            with urllib.request.urlopen(self.base_url + "/api/status", timeout=1) as r:
                return json.load(r)
        except (OSError, ValueError):
            return None

    def _signal_once(self, proc, sig):
        if proc is self._proc:
            proc.send_signal(sig)
        return GLib.SOURCE_REMOVE

    def _poll_ready(self, started):
        if self.state != "starting":
            self._poll_id = 0
            return GLib.SOURCE_REMOVE
        try:
            socket.create_connection((HOST, self.port), timeout=0.2).close()
        except OSError:
            if (GLib.get_monotonic_time() - started) / 1000 > READY_TIMEOUT_MS:
                self._poll_id = 0
                self._fail("Pat did not start listening in time.")
                self.stop()
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        self._poll_id = 0
        self.state = "running"
        self.emit("ready")
        return GLib.SOURCE_REMOVE

    def _on_line(self, stream, result, proc):
        try:
            line, _ = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:
            return
        self._append_log(line)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, proc)

    def _on_exit(self, proc, result, _data):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        if proc is not self._proc:
            return
        code = proc.get_exit_status() if proc.get_if_exited() else -1
        self._append_log(f"[pat-desktop] Pat exited (status {code}).")
        expected = self.state == "stopping"
        self._proc = None
        state.set("pid", None)
        self._cancel_poll()
        for source_id in self._stop_ids:
            source = GLib.MainContext.default().find_source_by_id(source_id)
            if source:
                source.destroy()
        self._stop_ids = []
        self.state = "stopped"
        if expected:
            self._notify_stopped()
        else:
            self._fail("Pat stopped unexpectedly.")

    def _notify_stopped(self):
        callback, self._on_stopped = self._on_stopped, None
        if callback:
            callback()

    def _cancel_poll(self):
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = 0

    def _fail(self, message):
        self._append_log(f"[pat-desktop] {message}")
        self.emit("failed", message)

    def _append_log(self, line):
        self.log.append(line)
        self.emit("log-line", line)
