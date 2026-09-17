"""Global (system-wide) hotkeys via pynput.

Hotkey strings use pynput's syntax, e.g. '<alt>+v', '<ctrl>+<shift>+c'. The set
is driven entirely by config so new bindings can be added from the settings
panel and re-registered live with `rebind()`.
"""
from __future__ import annotations

from typing import Callable

try:
    from pynput import keyboard
    _WIN = True
except Exception:  # pragma: no cover
    _WIN = False


class HotkeyManager:
    def __init__(self) -> None:
        self._listener = None
        self._map: dict[str, Callable[[], None]] = {}

    def rebind(self, bindings: dict[str, Callable[[], None]]) -> None:
        """Replace all hotkeys. `bindings` maps hotkey-string -> callback."""
        self._map = {k: v for k, v in bindings.items() if k}
        self.stop()
        if not _WIN or not self._map:
            return
        # GlobalHotKeys runs its own thread and dispatches on match.
        self._listener = keyboard.GlobalHotKeys(self._map)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
