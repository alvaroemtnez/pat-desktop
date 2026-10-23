# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
from gettext import gettext as _
from urllib.parse import urlsplit

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
gi.require_version("Soup", "3.0")

from gi.repository import Adw, Gio, GLib, Gtk, Soup, WebKit  # noqa: E402

from . import state  # noqa: E402
from .chrome import NavbarChrome  # noqa: E402

STATUS_POLL_S = 3
ZOOM_STEPS = [0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0]

# Pat's web UI offers to download new upstream releases. Pat Desktop is updated
# as a whole (a new Flatpak or AppImage), so that prompt would only mislead.
CONTENT_RULES = json.dumps([
    {"trigger": {"url-filter": "/api/new-release-check"}, "action": {"type": "block"}},
])

# WebKit answers "denied" to Notification.requestPermission() without a user
# gesture, even for an origin that is already granted. Per the spec it should
# resolve to the current "granted" state, which is what Pat's UI expects.
NOTIFICATION_SHIM = """
(() => {
  const N = window.Notification;
  if (!N || !N.requestPermission) return;
  const request = N.requestPermission.bind(N);
  N.requestPermission = function (callback) {
    const result = N.permission === 'granted' ? Promise.resolve('granted') : request();
    if (typeof callback === 'function') result.then(callback);
    return result;
  };
})();
"""


def _web_dirs():
    data = os.path.join(GLib.get_user_data_dir(), "pat-desktop", "webkit")
    cache = os.path.join(GLib.get_user_cache_dir(), "pat-desktop", "webkit")
    return data, cache


class PatWindow(Adw.ApplicationWindow):
    def __init__(self, app, backend):
        super().__init__(application=app, title="Pat")
        self.backend = backend
        self._status = None
        self._status_id = 0
        self._retry_id = 0
        self._quitting = False
        self._popups = set()

        self.set_default_size(state.get("width", 1100), state.get("height", 760))
        # Narrower than this, Pat collapses its navbar into its own menu button,
        # which would end up under the window controls.
        self.set_size_request(800, 480)
        if state.get("maximized"):
            self.maximize()

        self._build_ui()
        self._build_webview()
        self._install_actions()

        backend.connect("ready", self._on_backend_ready)
        backend.connect("failed", self._on_backend_failed)
        self.connect("close-request", self._on_close_request)

    # UI -------------------------------------------------------------------

    def _build_ui(self):
        self.menu = Gio.Menu()
        section = Gio.Menu()
        section.append(_("Pat _Configuration"), "win.configure")
        section.append(_("_Reload"), "win.reload")
        self.menu.append_section(None, section)
        zoom = Gio.Menu()
        zoom.append(_("Zoom _In"), "win.zoom-in")
        zoom.append(_("Zoom _Out"), "win.zoom-out")
        zoom.append(_("_Reset Zoom"), "win.zoom-reset")
        self.menu.append_section(None, zoom)
        section = Gio.Menu()
        section.append(_("Show _Log"), "win.show-log")
        section.append(_("Open _Data Folder"), "win.open-data")
        section.append(_("Re_start Pat"), "win.restart")
        self.menu.append_section(None, section)
        section = Gio.Menu()
        section.append(_("_Keyboard Shortcuts"), "app.shortcuts")
        section.append(_("_About Pat Desktop"), "app.about")
        self.menu.append_section(None, section)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)

        loading = Adw.StatusPage(title=_("Starting Pat…"))
        # Adw.Spinner needs libadwaita 1.6; the AppImage also runs on 1.5.
        spinner = (Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True))
        spinner.set_properties(halign=Gtk.Align.CENTER, width_request=48, height_request=48)
        loading.set_child(spinner)
        self.loading_page = loading
        self.stack.add_named(loading, "loading")

        self.error_page = Adw.StatusPage(icon_name="dialog-error-symbolic",
                                         title=_("Pat Is Not Running"))
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        restart = Gtk.Button(label=_("_Restart Pat"), use_underline=True,
                             action_name="win.restart")
        restart.add_css_class("pill")
        restart.add_css_class("suggested-action")
        log = Gtk.Button(label=_("Show _Log"), use_underline=True,
                         action_name="win.show-log")
        log.add_css_class("pill")
        buttons.append(restart)
        buttons.append(log)
        self.error_page.set_child(buttons)
        self.stack.add_named(self.error_page, "error")

    def _build_webview(self):
        data_dir, cache_dir = _web_dirs()
        self.session = WebKit.NetworkSession.new(data_dir, cache_dir)
        self.session.connect("download-started", self._on_download_started)

        self.content = WebKit.UserContentManager()
        self.content.add_script(WebKit.UserScript.new(
            NOTIFICATION_SHIM, WebKit.UserContentInjectedFrames.TOP_FRAME,
            WebKit.UserScriptInjectionTime.START, None, None))
        store = WebKit.UserContentFilterStore.new(os.path.join(cache_dir, "filters"))
        store.save("pat-desktop", GLib.Bytes.new(CONTENT_RULES.encode()), None,
                   self._on_filter_saved)

        self.webview = WebKit.WebView(network_session=self.session,
                                      user_content_manager=self.content)
        self.webview.get_context().connect("initialize-notification-permissions",
                                           self._grant_notifications)
        self._setup_view(self.webview)
        self.webview.set_zoom_level(state.get("zoom", 1.0))
        self.webview.connect("load-failed", self._on_load_failed)
        self.webview.connect("web-process-terminated", lambda v, _r: v.reload())

        # No header bar: the controls float over Pat's own navbar.
        self.chrome = NavbarChrome(self.webview, self.content, self.stack, self.menu)
        self.stack.add_named(self.chrome.web_overlay, "web")
        self.toasts = Adw.ToastOverlay(child=self.chrome.overlay)
        self.set_content(self.toasts)

    def _setup_view(self, view):
        settings = view.get_settings()
        settings.set_enable_developer_extras(bool(os.environ.get("PAT_DESKTOP_DEBUG")))
        settings.set_javascript_can_open_windows_automatically(True)
        view.connect("decide-policy", self._on_decide_policy)
        view.connect("create", self._on_create)
        view.connect("permission-request", self._on_permission_request)
        view.connect("show-notification", self._on_show_notification)

    def _on_filter_saved(self, store, result):
        try:
            self.content.add_filter(store.save_finish(result))
        except GLib.Error as e:
            print(f"pat-desktop: content filter unavailable: {e.message}")

    def _install_actions(self):
        def add(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_: callback())
            self.add_action(action)

        add("reload", self._reload)
        add("configure", lambda: self._open_path("/ui/config"))
        add("zoom-in", lambda: self._zoom(+1))
        add("zoom-out", lambda: self._zoom(-1))
        add("zoom-reset", lambda: self._zoom(0))
        add("show-log", self._show_log)
        add("open-data", self._open_data_folder)
        add("restart", self._restart)

    # Backend lifecycle ----------------------------------------------------

    def start(self):
        self.stack.set_visible_child_name("loading")
        self.loading_page.set_title(_("Starting Pat…"))
        self.backend.start()

    def _restart(self):
        self.stack.set_visible_child_name("loading")
        self.loading_page.set_title(_("Restarting Pat…"))
        self.backend.restart()

    def _on_backend_ready(self, _backend):
        self._grant_notifications()
        self.chrome.update_padding()
        self.webview.load_uri(self.backend.base_url + "/ui")
        self.stack.set_visible_child_name("web")
        if not self._status_id:
            self._status_id = GLib.timeout_add_seconds(STATUS_POLL_S, self._poll_status)
            self._poll_status()

    def _on_backend_failed(self, _backend, message):
        if self._quitting:
            return
        self.error_page.set_description(message)
        self.stack.set_visible_child_name("error")
        self._set_status(None)

    def _on_load_failed(self, view, _event, uri, error):
        # Pat briefly restarts its HTTP server after a configuration change.
        if self._is_local(uri) and self.backend.state == "running" and not self._retry_id:
            def retry():
                self._retry_id = 0
                view.load_uri(uri)
                return GLib.SOURCE_REMOVE
            self._retry_id = GLib.timeout_add(700, retry)
            return True
        return False

    # Status ---------------------------------------------------------------

    def _poll_status(self):
        if self.backend.state != "running":
            self._set_status(None)
            return GLib.SOURCE_CONTINUE
        msg = Soup.Message.new("GET", self.backend.base_url + "/api/status")
        self._soup = getattr(self, "_soup", None) or Soup.Session(timeout=2)
        self._soup.send_and_read_async(msg, GLib.PRIORITY_LOW, None, self._on_status)
        return GLib.SOURCE_CONTINUE

    def _on_status(self, session, result):
        try:
            data = json.loads(session.send_and_read_finish(result).get_data())
        except (GLib.Error, ValueError):
            data = None
        self._set_status(data)

    def _set_status(self, status):
        self._status = status

    # Navigation and windows ----------------------------------------------

    def _is_local(self, uri):
        if not uri or not self.backend.port:
            return False
        parts = urlsplit(uri)
        return (parts.scheme in ("http", "ws") and parts.hostname == "127.0.0.1"
                and parts.port == self.backend.port)

    def _open_path(self, path):
        if self.backend.state == "running":
            self.webview.load_uri(self.backend.base_url + path)

    def _reload(self):
        if self.backend.state == "running":
            self.webview.reload()

    def _launch_external(self, uri):
        Gtk.UriLauncher.new(uri).launch(self, None, None, None)

    def _on_decide_policy(self, view, decision, kind):
        T = WebKit.PolicyDecisionType
        if kind in (T.NAVIGATION_ACTION, T.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if not self._is_local(uri) and not uri.startswith(("about:", "blob:", "data:")):
                self._launch_external(uri)
                decision.ignore()
                return True
        elif kind == T.RESPONSE:
            response = decision.get_response()
            headers = response.get_http_headers()
            disposition = headers.get_one("Content-Disposition") if headers else None
            if (disposition and disposition.lower().startswith("attachment")) \
                    or not decision.is_mime_type_supported():
                decision.download()
                return True
        return False

    def _on_create(self, view, _action):
        # Pat opens forms (and some attachments) with window.open(); forms
        # report back to the composer and close themselves.
        popup = WebKit.WebView(related_view=view)
        self._setup_view(popup)
        popup.set_zoom_level(view.get_zoom_level())

        win = Adw.Window(transient_for=self, default_width=900, default_height=700,
                         title="Pat")
        title = Adw.WindowTitle(title="Pat")
        popup.bind_property("title", title, "title")
        header = Adw.HeaderBar(title_widget=title)
        toolbar = Adw.ToolbarView(content=popup)
        toolbar.add_top_bar(header)
        win.set_content(toolbar)

        def closed(*_args):
            self._popups.discard(win)
            win.destroy()
            return True

        self._popups.add(win)
        win.connect("close-request", closed)
        popup.connect("ready-to-show", lambda _v: win.present())
        popup.connect("close", closed)
        return popup

    # Permissions, notifications and downloads -----------------------------

    def _grant_notifications(self, *_args):
        # WebKit denies Notification.requestPermission() calls that do not come
        # from a user gesture, and Pat asks on page load. Pre-granting Pat's
        # origin makes Notification.permission "granted" from the start.
        if self.backend.port:
            origin = WebKit.SecurityOrigin.new_for_uri(self.backend.base_url)
            self.webview.get_context().initialize_notification_permissions([origin], [])

    def _on_permission_request(self, _view, request):
        if isinstance(request, WebKit.NotificationPermissionRequest):
            request.allow()
            return True
        return False

    def _on_show_notification(self, _view, notification):
        n = Gio.Notification.new(notification.get_title() or "Pat")
        if notification.get_body():
            n.set_body(notification.get_body())
        n.set_default_action("app.activate")
        self.get_application().send_notification(None, n)
        return True

    def _on_download_started(self, _session, download):
        download.connect("decide-destination", self._on_decide_destination)
        download.connect("finished", lambda d: self._download_finished(d))
        download.connect("failed", lambda _d, e: self.toasts.add_toast(
            Adw.Toast(title=_("Download failed: {}").format(e.message))))

    def _on_decide_destination(self, download, suggested):
        dialog = Gtk.FileDialog(initial_name=suggested or "attachment")
        downloads = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if downloads:
            dialog.set_initial_folder(Gio.File.new_for_path(downloads))

        def done(dlg, result):
            try:
                file = dlg.save_finish(result)
            except GLib.Error:
                download.cancel()
                return
            download.set_allow_overwrite(True)
            download.set_destination(file.get_path())

        dialog.save(self, None, done)
        return True

    def _download_finished(self, download):
        dest = download.get_destination()
        if not dest:
            return
        toast = Adw.Toast(title=_("Saved {}").format(os.path.basename(dest)),
                          button_label=_("Open"))
        toast.connect("button-clicked", lambda _t: Gtk.FileLauncher.new(
            Gio.File.new_for_path(dest)).launch(self, None, None, None))
        self.toasts.add_toast(toast)

    # Misc actions ---------------------------------------------------------

    def _zoom(self, direction):
        current = self.webview.get_zoom_level()
        if direction == 0:
            level = 1.0
        elif direction > 0:
            level = next((z for z in ZOOM_STEPS if z > current + 0.001), ZOOM_STEPS[-1])
        else:
            level = next((z for z in reversed(ZOOM_STEPS) if z < current - 0.001),
                         ZOOM_STEPS[0])
        self.webview.set_zoom_level(level)
        state.set("zoom", level)

    def _open_data_folder(self):
        path = os.path.join(GLib.get_user_data_dir(), "pat")
        os.makedirs(path, exist_ok=True)
        Gtk.FileLauncher.new(Gio.File.new_for_path(path)).launch(self, None, None, None)

    def _show_log(self):
        from .logwindow import LogWindow
        LogWindow(self, self.backend).present()

    # Closing --------------------------------------------------------------

    def _on_close_request(self, _win):
        if self._quitting:
            return False
        status = self._status or {}
        if status.get("connected") or status.get("dialing"):
            dialog = Adw.AlertDialog(
                heading=_("Quit During a Session?"),
                body=_("Pat is connected to a Winlink station. Quitting will abort "
                       "the session and messages may not be fully transferred."))
            dialog.add_response("cancel", _("_Cancel"))
            dialog.add_response("quit", _("_Quit"))
            dialog.set_response_appearance("quit", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.connect("response", lambda _d, r: r == "quit" and self.quit())
            dialog.present(self)
        else:
            self.quit()
        return True

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        state.set("maximized", self.is_maximized())
        if not self.is_maximized():
            width, height = self.get_default_size()
            state.set("width", width)
            state.set("height", height)
        for popup in list(self._popups):
            popup.destroy()
        self.loading_page.set_title(_("Stopping Pat…"))
        self.stack.set_visible_child_name("loading")
        app = self.get_application()
        self.backend.stop(app.quit)
