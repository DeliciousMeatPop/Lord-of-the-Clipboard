"""Lord of the Clipboard — entry point.

Wires the pieces together:
  config  ->  storage  ->  clipboard monitor (background thread)
                       ->  global hotkeys (Alt+V / Alt+B, rebindable)
                       ->  pywebview window (the pretty UI)
"""
from __future__ import annotations

import webview  # pywebview

from . import config as cfg
from . import source_app, storage
from .api import Api
from .clipboard_monitor import ClipboardMonitor
from .hotkeys import HotkeyManager
from .paths import WEB_DIR, ensure_dirs


def build():
    ensure_dirs()
    config = cfg.load()
    storage.init()

    api = Api(config)

    window = webview.create_window(
        title="Lord of the Clipboard",
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=760,
        height=620,
        min_size=(520, 420),
        frameless=True,
        easy_drag=False,
        on_top=True,
        background_color="#14141c",
        hidden=True,  # lives in the background until a hotkey summons it
    )
    api.window = window

    # New clips push into the UI (only matters while the window is visible).
    def on_new_clip(row):
        try:
            window.evaluate_js("window.__lotc && window.__lotc.onNewClip()")
        except Exception:
            pass

    monitor = ClipboardMonitor(config, on_new_clip=on_new_clip)
    api.monitor = monitor

    hk = HotkeyManager()

    def summon(favorites: bool):
        # Remember which app we're pasting back into, then show + focus.
        api.last_target_hwnd = source_app.get_foreground_hwnd()
        api._favorites_mode = favorites
        try:
            window.show()
            window.evaluate_js(
                f"window.__lotc && window.__lotc.onSummon({str(favorites).lower()})"
            )
        except Exception:
            pass

    def rebind():
        binds = config.get("hotkeys", {})
        mapping = {}
        if binds.get("show_window"):
            mapping[binds["show_window"]] = lambda: summon(False)
        if binds.get("show_favorites"):
            mapping[binds["show_favorites"]] = lambda: summon(True)
        hk.rebind(mapping)

    api.rebind_hotkeys = rebind

    def on_start():
        monitor.start()
        rebind()

    return window, on_start


def main():
    window, on_start = build()
    # gui='edgechromium' -> WebView2 on Windows for modern CSS.
    webview.start(on_start, gui="edgechromium", debug=False)


if __name__ == "__main__":
    main()
