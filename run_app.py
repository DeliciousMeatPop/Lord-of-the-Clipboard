"""Entry point for frozen (PyInstaller) builds.

The package uses relative imports, so PyInstaller needs a plain script that
imports the package rather than running src/app.py directly.

This wrapper is also the outermost crash catcher: because the app is built
windowed (no console), an unhandled error — including an import failure from a
missing bundled module — would otherwise vanish silently. Here we log the full
traceback next to the exe and pop a message box so failures are never invisible.
"""
import ctypes
import os
import sys
import traceback


def _data_dir():
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(base, "data")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _report(tb: str):
    try:
        with open(os.path.join(_data_dir(), "lotc-crash.log"), "a", encoding="utf-8") as fh:
            fh.write(tb + "\n" + "=" * 60 + "\n")
    except Exception:
        pass
    try:
        ctypes.windll.user32.MessageBoxW(
            0, tb[-1800:], "Lord of the Clipboard — startup error", 0x10)
    except Exception:
        pass


def main():
    try:
        from src.app import main as run
        run()
    except BaseException:
        _report(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
