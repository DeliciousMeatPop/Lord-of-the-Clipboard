"""Lord of the Clipboard — entry point.

Wires the pieces together:
  config  ->  storage  ->  clipboard monitor (background thread)
                       ->  global hotkeys (Alt+V / Alt+B, rebindable)
                       ->  pywebview window (the pretty UI)
"""
from __future__ import annotations

import logging
import threading

import webview  # pywebview

from . import config as cfg
from . import source_app, storage, sync
from ._version import __version__
from .api import Api
from .clipboard_monitor import ClipboardMonitor
from .hotkeys import HotkeyManager
from .paths import DATA_DIR, WEB_DIR, ensure_dirs
from .tray import Tray

log = logging.getLogger("lotc")


def _setup_logging():
    ensure_dirs()
    logging.basicConfig(
        filename=str(DATA_DIR / "lotc.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _fatal_dialog(msg: str):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, msg[-1800:], "Lord of the Clipboard — error", 0x10)
    except Exception:
        pass


def build():
    ensure_dirs()
    config = cfg.load()
    storage.init()
    log.info("config loaded, storage ready")

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
            tray.stop()
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    api.quit_app = quit_app

    def check_update_bg():
        from . import updater
        upd = config.get("update", {})
        if not upd.get("check_on_start"):
            return
        info = updater.check(upd.get("repo", ""))
        if info.get("ok") and info.get("available"):
            if upd.get("auto_install") and info.get("url") and updater.is_frozen():
                api.install_update(info["url"])
            else:
                try:
                    import json as _json
                    window.evaluate_js(
                        "window.__lotc && window.__lotc.onUpdate(" + _json.dumps(info) + ")")
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
        # Runs on a worker thread after the GUI loop starts. Exceptions here are
        # otherwise swallowed, so guard the whole thing and surface failures.
        try:
            seed_examples()
            storage.prune_expired()
            if config.get("sync", {}).get("import_on_start"):
                try:
                    sync.import_from(config.get("sync", {}).get("folder", ""))
                except Exception:
                    log.exception("sync import failed")
            monitor.start()
            log.info("monitor started")
            rebind()
            log.info("hotkeys bound: %s", config.get("hotkeys", {}))
            threading.Thread(target=expiry_loop, daemon=True).start()
            threading.Thread(target=check_update_bg, daemon=True).start()
            try:
                tray.start(
                    on_open=lambda: summon(False),
                    on_favorites=lambda: summon(True),
                    on_toggle_pause=monitor.toggle_pause,
                    on_quit=quit_app,
                )
                log.info("tray started")
            except Exception:
                log.exception("tray failed to start")
            # First launch: show the window once so it's obvious the app is
            # running and where it lives (afterwards it stays hidden until Alt+V).
            marker = DATA_DIR / ".shown_once"
            if not marker.exists():
                try:
                    summon(False)
                    marker.write_text("1", encoding="utf-8")
                except Exception:
                    log.exception("first-run show failed")
        except Exception:
            log.exception("on_start failed")
            _fatal_dialog("Startup failed:\n\n" + __import__("traceback").format_exc())

    return window, on_start


def main():
    _setup_logging()
    try:
        log.info("starting v%s", __version__)
        window, on_start = build()
        log.info("window created; entering GUI loop")
        # gui='edgechromium' -> WebView2 on Windows for modern CSS.
        webview.start(on_start, gui="edgechromium", debug=False)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        log.exception("fatal error in main")
        _fatal_dialog("Lord of the Clipboard could not start:\n\n" + tb)
        raise


if __name__ == "__main__":
    main()
