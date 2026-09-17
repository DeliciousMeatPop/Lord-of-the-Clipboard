"""Reading from and writing to the Windows clipboard, plus paste transforms.

`read()` snapshots whatever is on the clipboard (text / image / file list).
`copy_*` puts a stored clip back, and `paste_into(hwnd)` re-focuses the app the
window was summoned from and fires Ctrl+V.

We hand the monitor a way to recognise our own writes (via the clipboard
sequence number) so restoring a clip doesn't get re-captured as new history.
"""
from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import win32clipboard
    import win32con
    from PIL import Image, ImageGrab
    from pynput.keyboard import Controller, Key
    import win32gui
    _WIN = True
except Exception:  # pragma: no cover - non-Windows
    _WIN = False


@dataclass
class ClipData:
    type: str                     # 'text' | 'image' | 'files'
    text: str = ""                # for text
    html: str = ""                # rich CF_HTML fragment, when present
    image: object = None          # PIL.Image for image
    paths: Optional[list] = None  # for files


# CF_HTML is a registered format; resolve its id once.
_CF_HTML = 0
if _WIN:
    try:
        _CF_HTML = win32clipboard.RegisterClipboardFormat("HTML Format")
    except Exception:
        _CF_HTML = 0


# ----------------------------------------------------------------------------- read
def read() -> Optional[ClipData]:
    """Snapshot the current clipboard. Returns None if it holds nothing we handle."""
    if not _WIN:
        return None
    # ImageGrab handles both bitmap images and CF_HDROP file lists cleanly.
    try:
        grabbed = ImageGrab.grabclipboard()
    except Exception:
        grabbed = None
    if isinstance(grabbed, list) and grabbed:
        return ClipData(type="files", paths=[str(p) for p in grabbed])
    if grabbed is not None and not isinstance(grabbed, list):
        return ClipData(type="image", image=grabbed)
    text = _get_text()
    if text:
        return ClipData(type="text", text=text, html=_get_html())
    return None


def _get_html() -> str:
    """Return the CF_HTML *fragment* (the marked-up body), or '' if none."""
    if not _CF_HTML:
        return ""
    for _ in range(2):
        try:
            win32clipboard.OpenClipboard()
            try:
                if not win32clipboard.IsClipboardFormatAvailable(_CF_HTML):
                    return ""
                raw = win32clipboard.GetClipboardData(_CF_HTML)
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.05)
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        # CF_HTML has a header with StartFragment/EndFragment byte offsets;
        # the human-readable markers are good enough and version-proof.
        start = raw.find("<!--StartFragment-->")
        end = raw.find("<!--EndFragment-->")
        if start != -1 and end != -1:
            return raw[start + len("<!--StartFragment-->"):end].strip()
        # No fragment markers: fall back to everything after the header block.
        body = raw.split("<html", 1)
        return ("<html" + body[1]) if len(body) > 1 else ""
    return ""


def _get_text() -> str:
    for _ in range(3):  # clipboard can be briefly locked by the source app
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) or ""
                return ""
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    return ""


def sequence_number() -> int:
    if not _WIN:
        return 0
    try:
        return win32clipboard.GetClipboardSequenceNumber()
    except Exception:
        return 0


# ----------------------------------------------------------------------------- write
def copy_text(text: str) -> None:
    if not _WIN:
        return
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            return
        except Exception:
            time.sleep(0.05)


def copy_image(path: str) -> None:
    if not _WIN:
        return
    try:
        img = Image.open(path).convert("RGB")
        out = io.BytesIO()
        img.save(out, "BMP")
        # A CF_DIB is a BMP file minus its 14-byte BITMAPFILEHEADER.
        data = out.getvalue()[14:]
        out.close()
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, data)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass


def copy_files(paths: list) -> None:
    """Best-effort: put the newline-joined paths on the clipboard as text.

    (Full CF_HDROP restore is a later refinement; text of the paths is useful
    now and never fails.)
    """
    copy_text("\n".join(paths))


# ----------------------------------------------------------------------------- paste
def paste_into(hwnd: int, restore_focus: bool = True) -> None:
    """Re-focus `hwnd` (the app the window was summoned from) and press Ctrl+V."""
    if not _WIN:
        return
    try:
        if restore_focus and hwnd:
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            time.sleep(0.08)  # let focus settle before the keystroke
        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press("v")
            kb.release("v")
    except Exception:
        pass


# ----------------------------------------------------------------------------- transforms
def _collapse_blank_lines(t: str) -> str:
    import re
    return re.sub(r"\n\s*\n+", "\n\n", t)


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "plain": lambda t: t,                                  # we only store plain text anyway
    "trim": lambda t: t.strip(),
    "upper": lambda t: t.upper(),
    "lower": lambda t: t.lower(),
    "title": lambda t: t.title(),
    "sentence": lambda t: (t[:1].upper() + t[1:]) if t else t,
    "single_line": lambda t: " ".join(t.split()),
    "collapse_blanks": _collapse_blank_lines,
    "no_urls_tracking": lambda t: t.split("?")[0] if t.startswith(("http://", "https://")) else t,
}


def apply_transform(text: str, name: str) -> str:
    fn = TRANSFORMS.get(name)
    return fn(text) if fn else text
