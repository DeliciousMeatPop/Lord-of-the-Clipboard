"""Lord of the Clipboard — entry point.

Wires the pieces together:
  config  ->  storage  ->  clipboard monitor (background thread)
                       ->  global hotkeys (Alt+V / Alt+B, rebindable)
                       ->  pywebview window (the pretty UI)
"""
from __future__ import annotations

import threading

import webview  # pywebview

from . import config as cfg
from . import source_app, storage, sync
from ._version import __version__
from .api import Api
from .clipboard_monitor import ClipboardMonitor
from .hotkeys import HotkeyManager
from .paths import WEB_DIR, ensure_dirs
from .tray import Tray


def build():
    ensure_dirs()
    config = cfg.load()
    storage.init()

    api = Api(config)

    window = webview.create_window(
        title=f"Lord of the Clipboard v{__version__}",
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
    tray = Tray(accent=config.get("ui", {}).get("accent", "#7c5cff"))

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

    def quit_app():
        try:
            monitor.stop()
            hk.stop()
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    def expiry_loop():
        # Sweep out expired (secret) clips every few minutes.
        while not monitor._stop.wait(300):
            try:
                storage.prune_expired()
            except Exception:
                pass

    def seed_examples():
        # One-time: drop in a couple of example snippets so the tokens are
        # discoverable. Guarded by a marker file so we never re-add them.
        from .paths import DATA_DIR
        marker = DATA_DIR / ".seeded"
        if marker.exists():
            return
        try:
            storage.create_snippet("log line", "{date} {time} — ")
            storage.create_snippet("reply to telegram", "Re: {telegram}\n\n")
            storage.create_snippet("email signoff", "Thanks,\n{name}")
            marker.write_text("1", encoding="utf-8")
        except Exception:
            pass

    def on_start():
        seed_examples()
        storage.prune_expired()
        # Optional: pull synced favorites/snippets on launch.
        if config.get("sync", {}).get("import_on_start"):
            try:
                sync.import_from(config.get("sync", {}).get("folder", ""))
            except Exception:
                pass
        monitor.start()
        rebind()
        threading.Thread(target=expiry_loop, daemon=True).start()
        tray.start(
            on_open=lambda: summon(False),
            on_favorites=lambda: summon(True),
            on_toggle_pause=monitor.toggle_pause,
            on_quit=quit_app,
        )

    return window, on_start


def main():
    window, on_start = build()
    # gui='edgechromium' -> WebView2 on Windows for modern CSS.
    webview.start(on_start, gui="edgechromium", debug=False)


if __name__ == "__main__":
    main()
