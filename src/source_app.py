"""Figure out where a clip came from.

For any app we record the process name, exe path and window title. For
browsers we go a step further and read the active tab's URL from the address
bar via Windows UI Automation, then normalize it to a domain (e.g.
'steamdb.info', 'web.telegram.org') so you can filter history by site.

All of this is Windows-only and entirely best-effort: every lookup is wrapped
so a failure just yields blanks rather than crashing the capture loop.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlparse

# Windows-only imports — guarded so the module can at least be imported elsewhere.
try:
    import psutil
    import win32gui
    import win32process
    _WIN = True
except Exception:  # pragma: no cover - non-Windows
    _WIN = False

# UI Automation is optional; browser-URL detection degrades gracefully without it.
try:
    import uiautomation as _uia
    _UIA = True
except Exception:
    _UIA = False

# Process names we treat as browsers (lowercased).
_BROWSERS = {
    "chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe",
    "vivaldi.exe", "librewolf.exe", "chromium.exe", "arc.exe",
}


@dataclass
class Source:
    app: str = ""          # process name, e.g. 'chrome.exe'
    exe: str = ""          # full path to the executable
    title: str = ""        # foreground window title
    url: str = ""          # active-tab URL (browsers only)
    domain: str = ""       # normalized host from url

    def as_dict(self) -> dict:
        return asdict(self)


def get_foreground_hwnd() -> int:
    """Handle of the window that currently has focus (0 if unavailable)."""
    if not _WIN:
        return 0
    try:
        return win32gui.GetForegroundWindow()
    except Exception:
        return 0


def _domain_from_url(url: str) -> str:
    try:
        host = urlparse(url if "://" in url else "http://" + url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _browser_url(hwnd: int) -> str:
    """Read the address-bar text of a Chromium/Firefox window via UI Automation."""
    if not _UIA:
        return ""
    try:
        ctrl = _uia.ControlFromHandle(hwnd)
        if ctrl is None:
            return ""
        # Chromium/Edge and Firefox both expose an Edit control named like
        # "Address and search bar" / "Search or enter address".
        for name in ("Address and search bar", "Search or enter address",
                     "Address field", "Address"):
            edit = ctrl.EditControl(searchDepth=20, Name=name)
            if edit.Exists(maxSearchSeconds=0.4):
                val = edit.GetValuePattern().Value
                if val:
                    return val
        # Fallback: first Edit control that looks like a URL/host.
        edit = ctrl.EditControl(searchDepth=20)
        if edit.Exists(maxSearchSeconds=0.3):
            val = edit.GetValuePattern().Value or ""
            if "." in val and " " not in val.strip():
                return val
    except Exception:
        pass
    return ""


def capture(hwnd: Optional[int] = None) -> Source:
    """Build a Source for the given (or current foreground) window."""
    src = Source()
    if not _WIN:
        return src
    try:
        if hwnd is None:
            hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return src
        src.title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            proc = psutil.Process(pid)
            src.app = (proc.name() or "").lower()
            src.exe = proc.exe() or ""
        except Exception:
            pass
        if src.app in _BROWSERS:
            src.url = _browser_url(hwnd)
            src.domain = _domain_from_url(src.url)
    except Exception:
        pass
    return src
