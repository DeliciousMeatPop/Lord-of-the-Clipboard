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
    import win32api
    import win32gui
    import win32process
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
def copy_text(text: str) -> bool:
    """Put text on the clipboard. Returns True on success."""
    if not _WIN:
        return False
    text = "" if text is None else str(text)
    for _ in range(5):  # the clipboard is often briefly locked by another app
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                # SetClipboardText handles the UTF-16 buffer allocation reliably.
                win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            time.sleep(0.06)
    return False


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
    """Focus the target external window and press Ctrl+V.

    Windows blocks a plain SetForegroundWindow from a background thread, so we
    briefly attach our input thread to the target's before forcing focus — the
    trick every paste tool uses.
    """
    if not _WIN:
        return
    try:
        if restore_focus and hwnd and win32gui.IsWindow(hwnd):
            try:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                cur = win32api.GetCurrentThreadId()
                target = win32process.GetWindowThreadProcessId(hwnd)[0]
                win32process.AttachThreadInput(cur, target, True)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                finally:
                    win32process.AttachThreadInput(cur, target, False)
            except Exception:
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
            time.sleep(0.15)  # let focus settle before the keystroke
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


def _strip_tracking(t: str) -> str:
    """Drop tracking query params (utm_*, fbclid, gclid, ref, …) from a URL."""
    import re
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
    s = t.strip()
    if not s.startswith(("http://", "https://")):
        return t
    junk = re.compile(r"^(utm_|fbclid|gclid|mc_|igshid|si$|ref$|ref_src$|spm$|_hsenc$|_hsmi$)", re.I)
    p = urlparse(s)
    kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not junk.match(k)]
    return urlunparse(p._replace(query=urlencode(kept)))


def _remove_line_numbers(t: str) -> str:
    import re
    return "\n".join(re.sub(r"^\s*\d+[:.\)\]\s]\s?", "", ln) for ln in t.splitlines())


def _json_pretty(t: str) -> str:
    import json
    try:
        return json.dumps(json.loads(t), indent=2, ensure_ascii=False)
    except Exception:
        return t


def _b64_encode(t: str) -> str:
    import base64
    return base64.b64encode(t.encode("utf-8")).decode("ascii")


def _b64_decode(t: str) -> str:
    import base64
    try:
        return base64.b64decode(t.strip()).decode("utf-8", "replace")
    except Exception:
        return t


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "plain": lambda t: t,                                  # we only store plain text anyway
    "trim": lambda t: t.strip(),
    "upper": lambda t: t.upper(),
    "lower": lambda t: t.lower(),
    "title": lambda t: t.title(),
    "sentence": lambda t: (t[:1].upper() + t[1:]) if t else t,
    "single_line": lambda t: " ".join(t.split()),
    "join_lines": lambda t: " ".join(ln.strip() for ln in t.splitlines() if ln.strip()),
    "collapse_blanks": _collapse_blank_lines,
    "strip_tracking": _strip_tracking,
    "remove_line_numbers": _remove_line_numbers,
    "json_pretty": _json_pretty,
    "base64_encode": _b64_encode,
    "base64_decode": _b64_decode,
}


def apply_transform(text: str, name: str) -> str:
    fn = TRANSFORMS.get(name)
    return fn(text) if fn else text
