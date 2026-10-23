# SPDX-License-Identifier: GPL-3.0-or-later
"""Window chrome merged into Pat's own navigation bar.

Instead of a header bar above Pat's UI, the window controls and the main menu
float over the right end of Pat's top navbar, and the empty parts of that
navbar move the window like a title bar does.
"""

import json

from gi.repository import Gtk, WebKit

HANDLER = "patDesktopNavbar"

# Reports the empty horizontal stretches of Pat's fixed top navbar, which the
# window turns into drag areas. Empty while a Bootstrap modal is open, so its
# backdrop still closes it.
NAVBAR_SCRIPT = """
(() => {
  const INTERACTIVE = 'a, button, input, select, textarea, label, [role=button], [data-toggle]';
  const MIN_SPAN = 8;
  const BASE_PADDING = 15;  // Bootstrap's own container padding
  let queued = false;

  // Pad Pat's navbar container just enough to keep its items clear of the
  // window controls, whose width the app publishes as a CSS variable.
  function makeRoom(nav) {
    const container = nav.querySelector(':scope > .container, :scope > .container-fluid');
    if (!container) return;
    const controls = parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--pat-desktop-controls')) || 0;
    const free = window.innerWidth - container.getBoundingClientRect().right;
    const padding = BASE_PADDING + Math.max(0, Math.ceil(controls - free));
    if (container.style.paddingRight !== padding + 'px') {
      container.style.paddingRight = padding + 'px';
    }
  }

  function report() {
    queued = false;
    // Only Pat's own pages, not Winlink forms in popup windows (which share
    // this script and message handler).
    if (!location.pathname.startsWith('/ui')) return;
    const nav = document.querySelector('.navbar-fixed-top');
    const msg = { spans: [] };
    if (nav) makeRoom(nav);
    if (nav && !document.body.classList.contains('modal-open')) {
      const n = nav.getBoundingClientRect();
      const holes = [...nav.querySelectorAll(INTERACTIVE)]
        .map(e => e.getBoundingClientRect())
        .filter(r => r.width > 0 && r.height > 0 && r.bottom > n.top && r.top < n.bottom)
        .map(r => [r.left, r.right])
        .sort((a, b) => a[0] - b[0]);
      let x = n.left;
      for (const [left, right] of holes) {
        if (left - x >= MIN_SPAN) msg.spans.push([x, left - x]);
        x = Math.max(x, right);
      }
      if (n.right - x >= MIN_SPAN) msg.spans.push([x, n.right - x]);
      msg.top = n.top;
      msg.height = n.height;
    }
    window.webkit.messageHandlers.%s.postMessage(JSON.stringify(msg));
  }

  const schedule = () => {
    if (!queued) { queued = true; requestAnimationFrame(report); }
  };
  addEventListener('resize', schedule);
  addEventListener('load', schedule);
  document.addEventListener('DOMContentLoaded', () => {
    const watch = { subtree: true, childList: true, attributes: true, characterData: true };
    const nav = document.querySelector('.navbar-fixed-top');
    if (nav) new MutationObserver(schedule).observe(nav, watch);
    new MutationObserver(schedule).observe(document.body, { attributes: true, attributeFilter: ['class'] });
    schedule();
  });
})();
""" % HANDLER

# Publishes the width of the window controls to the page (see makeRoom()).
CONTROLS_CSS = ":root { --pat-desktop-controls: %dpx; }"
CONTROLS_MARGIN = 6


class NavbarChrome:
    """Puts `menu` and the window controls over Pat's navbar in `webview`.

    `page` is what the window shows (it contains the web view), `web_overlay`
    wraps just the web view and holds the drag areas.
    """

    def __init__(self, webview, content_manager, page, menu, on_resized):
        """`on_resized` is called when controls_css() changes."""
        self.webview = webview
        self.content = content_manager
        self._handles = []
        self._last_spans = None

        self.web_overlay = Gtk.Overlay(child=webview)

        # A header bar would keep its two halves equally wide to centre the
        # title, doubling its width, so this is a plain box with the same
        # native window buttons, in the order of the desktop's button layout.
        box = Gtk.Box(spacing=6, margin_start=CONTROLS_MARGIN, margin_end=CONTROLS_MARGIN,
                      valign=Gtk.Align.CENTER)
        box.append(Gtk.WindowControls(side=Gtk.PackType.START))
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                     primary=True, tooltip_text="Main Menu")
        menu_button.add_css_class("flat")
        box.append(menu_button)
        box.append(Gtk.WindowControls(side=Gtk.PackType.END))
        self.controls = Gtk.WindowHandle(child=box, halign=Gtk.Align.END,
                                         valign=Gtk.Align.START)
        self.overlay = Gtk.Overlay(child=page)
        self.overlay.add_overlay(self.controls)

        content_manager.add_script(WebKit.UserScript.new(
            NAVBAR_SCRIPT, WebKit.UserContentInjectedFrames.TOP_FRAME,
            WebKit.UserScriptInjectionTime.START, None, None))
        content_manager.register_script_message_handler(HANDLER, None)
        content_manager.connect(f"script-message-received::{HANDLER}", self._on_navbar)
        webview.connect("notify::zoom-level", lambda *_: on_resized())
        Gtk.Settings.get_default().connect("notify::gtk-decoration-layout",
                                           lambda *_: on_resized())

    def controls_css(self):
        """CSS publishing the controls' width (in CSS pixels) to Pat's page."""
        width = self.controls.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        return CONTROLS_CSS % round(width / self.webview.get_zoom_level())

    def _on_navbar(self, _manager, value):
        try:
            data = json.loads(value.to_string())
        except ValueError:
            return
        zoom = self.webview.get_zoom_level()
        limit = self.web_overlay.get_width() - self.controls.get_width()
        spans = []
        for x, width in data.get("spans", []):
            x, width = round(x * zoom), round(width * zoom)
            width = min(width, limit - x)
            if width > 0:
                spans.append((x, width))
        top = round(data.get("top", 0) * zoom)
        height = round(data.get("height", 0) * zoom)
        if height:
            # Centre the controls on Pat's navbar.
            own = self.controls.measure(Gtk.Orientation.VERTICAL, -1)[1]
            self.controls.set_margin_top(max(0, top + (height - own) // 2))
        key = (tuple(spans), top, height)
        if key == self._last_spans:
            return
        self._last_spans = key

        for handle in self._handles:
            self.web_overlay.remove_overlay(handle)
        self._handles = []
        for x, width in spans:
            handle = Gtk.WindowHandle(halign=Gtk.Align.START, valign=Gtk.Align.START,
                                      margin_start=x, margin_top=top,
                                      width_request=width, height_request=height)
            self.web_overlay.add_overlay(handle)
            self._handles.append(handle)
