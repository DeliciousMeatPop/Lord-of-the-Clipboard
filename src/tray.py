"""System tray icon (pystray).

Gives the app a home in the notification area: open the window, jump to
favorites, pause/resume capture, or quit. Runs in its own thread; callbacks are
supplied by the app so the tray stays decoupled from the window/monitor.

Degrades safely: if pystray/Pillow aren't available the app just runs without a
tray icon.
"""
from __future__ import annotations

from typing import Callable

try:
    import pystray
    from PIL import Image, ImageDraw
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


def _make_icon_image(accent: str = "#7c5cff"):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 58, 58], radius=14, fill=(26, 26, 36, 255))
    # a little crown
    try:
        rgb = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        rgb = (124, 92, 255)
    d.polygon([(18, 44), (18, 26), (26, 34), (32, 22), (38, 34), (46, 26), (46, 44)], fill=rgb)
    d.rectangle([18, 44, 46, 49], fill=rgb)
    return img


class Tray:
    def __init__(self, accent: str = "#7c5cff"):
        self._icon = None
        self.accent = accent

    def start(
        self,
        on_open: Callable[[], None],
        on_favorites: Callable[[], None],
        on_toggle_pause: Callable[[], bool],
        on_quit: Callable[[], None],
    ) -> None:
        if not _HAVE:
            return

        def _pause_text(item):
            return "Resume capture" if getattr(self, "_paused", False) else "Pause capture"

        def _do_pause(icon, item):
            self._paused = on_toggle_pause()

        def _quit(icon, item):
            try:
                icon.stop()
            finally:
                on_quit()

        menu = pystray.Menu(
            pystray.MenuItem("Open  (Alt+V)", lambda i, it: on_open(), default=True),
            pystray.MenuItem("Favorites  (Alt+B)", lambda i, it: on_favorites()),
            pystray.MenuItem(_pause_text, _do_pause),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit),
        )
        self._icon = pystray.Icon(
            "lotc", _make_icon_image(self.accent), "Lord of the Clipboard", menu
        )
        # run_detached lets it live alongside the pywebview GUI loop.
        try:
            self._icon.run_detached()
        except Exception:
            import threading
            threading.Thread(target=self._icon.run, daemon=True).start()

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
