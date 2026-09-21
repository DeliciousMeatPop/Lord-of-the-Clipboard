"""The bridge exposed to the web UI as `window.pywebview.api.*`.

IMPORTANT: the object passed to pywebview as `js_api` must not hold any
reference to the pywebview window, the monitor threads, or any other
non-JSON object. pywebview walks the exposed object when marshalling calls,
and reaching `window.native` (the WebView2 COM tree) sends it into infinite
recursion / cross-thread COM errors — which is what froze the UI on every
click. So all live objects live in the module-level CTX, and the window is
fetched on demand from `webview.windows`.

Long/native actions (paste, focus, topmost) run on a worker thread so a JS
call never blocks the UI thread.
"""
from __future__ import annotations

import base64
import os
import threading
from typing import Any, Optional

import webview

from . import config as cfg
from . import importers, markup, paster, source_app, storage, sync, templates, updater
from ._version import __version__
from .paths import DATA_DIR

# Live, non-serializable state — deliberately NOT stored on the exposed Api.
CTX: dict[str, Any] = {
    "monitor": None,        # ClipboardMonitor
    "last_target_hwnd": 0,  # external window we paste into
    "on_top": True,
    "favorites_mode": False,
    "quit": None,           # callable to quit the app
    "rebind": None,         # callable to re-register hotkeys
}


def _window():
    try:
        return webview.windows[0]
    except Exception:
        return None


def _async(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


class Api:
    def __init__(self, config: dict):
        self.config = config  # a plain JSON dict — safe for pywebview to see

    # -- reads --------------------------------------------------------------
    def list_clips(self, opts: Optional[dict] = None) -> list[dict[str, Any]]:
        o = opts or {}
        return storage.list_clips(
            query=o.get("query", ""),
            favorites_only=o.get("favorites_only", False),
            snippets_only=o.get("snippets_only", False),
            content_type=o.get("content_type", ""),
            category=o.get("category", ""),
            source_app=o.get("source_app", ""),
            domain=o.get("domain", ""),
            day=o.get("day", ""),
            sort=o.get("sort", "used"),
            limit=o.get("limit", 500),
            offset=o.get("offset", 0),
        )

    def list_by_day(self, opts: Optional[dict] = None) -> list[dict[str, Any]]:
        """Group clips into day buckets. A clip appears under its copied-day and,
        if different, its last-used-day (tagged so the UI can label each)."""
        import datetime as _dt

        rows = self.list_clips({**(opts or {}), "sort": "created",
                                "limit": (opts or {}).get("limit", 1000)})
        buckets: dict[str, list[dict]] = {}

        def day_of(epoch: float) -> str:
            return _dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")

        for r in rows:
            copied_day = day_of(r["created_at"])
            buckets.setdefault(copied_day, []).append({**r, "_reason": "copied"})
            if r.get("last_used_at"):
                used_day = day_of(r["last_used_at"])
                if used_day != copied_day:
                    buckets.setdefault(used_day, []).append({**r, "_reason": "used"})

        out = []
        for day in sorted(buckets.keys(), reverse=True):
            items = sorted(
                buckets[day],
                key=lambda x: x["last_used_at"] if x["_reason"] == "used" else x["created_at"],
                reverse=True,
            )
            out.append({"day": day, "clips": items})
        return out

    def sources(self) -> dict:
        return storage.sources()

    def days(self) -> list[str]:
        return storage.days()

    def content_types(self) -> list:
        return storage.content_types()

    def categories(self) -> list[str]:
        return storage.categories()

    def image_data_url(self, clip_id: int) -> str:
        clip = storage.get_clip(clip_id)
        if not clip or clip["type"] != "image":
            return ""
        try:
            with open(DATA_DIR / clip["content"], "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("ascii")
            return f"data:image/png;base64,{b64}"
        except Exception:
            return ""

    def preview_markup(self, clip_id: int, target: str) -> str:
        clip = storage.get_clip(clip_id)
        return markup.to_markup(clip, target) if clip else ""

    # -- mutations ----------------------------------------------------------
    def toggle_favorite(self, clip_id: int) -> bool:
        return storage.toggle_favorite(clip_id)

    def set_category(self, clip_id: int, category: str) -> None:
        storage.set_category(clip_id, category)

    def delete_clip(self, clip_id: int) -> None:
        storage.delete_clip(clip_id)

    def clear_history(self, keep_favorites: bool = True) -> None:
        storage.clear_history(keep_favorites)

    # -- copy / paste -------------------------------------------------------
    def _put_on_clipboard(self, clip: dict, target_format: str = "", transform: str = "",
                          override_text: str = None) -> None:
        if clip["type"] == "text":
            if override_text is not None:
                text = override_text
            else:
                text = markup.to_markup(clip, target_format) if target_format else clip["content"]
            if transform:
                text = paster.apply_transform(text, transform)
            paster.copy_text(text)
        elif clip["type"] == "image":
            paster.copy_image(str(DATA_DIR / clip["content"]))
        elif clip["type"] == "files":
            paster.copy_files((clip["content"] or "").split("\n"))
        mon = CTX.get("monitor")
        if mon:
            mon.note_self_write()

    def copy_clip(self, clip_id: int, target_format: str = "", transform: str = "") -> bool:
        clip = storage.get_clip(clip_id)
        if not clip:
            return False
        _async(lambda: (self._put_on_clipboard(clip, target_format, transform),
                        storage.mark_used(clip_id)))
        return True

    def paste_clip(self, clip_id: int, target_format: str = "", transform: str = "") -> bool:
        clip = storage.get_clip(clip_id)
        if not clip:
            return False
        _async(lambda: self._do_paste(clip, clip_id, target_format, transform))
        return True

    def paste_many(self, clip_ids: list, sep: str = "\n") -> bool:
        clips = [storage.get_clip(cid) for cid in (clip_ids or [])]
        clips = [c for c in clips if c and c["type"] == "text"]
        if not clips:
            return False

        def work():
            paster.copy_text(sep.join(c["content"] or "" for c in clips))
            mon = CTX.get("monitor")
            if mon:
                mon.note_self_write()
            for c in clips:
                storage.mark_used(c["id"])
            self._deliver_paste()
        _async(work)
        return True

    def paste_snippet(self, clip_id: int, values: dict = None) -> bool:
        clip = storage.get_clip(clip_id)
        if not clip:
            return False
        text = clip.get("content") or ""
        for key, val in (values or {}).items():
            text = text.replace("{" + key + "}", val)
        _async(lambda: self._do_paste(clip, clip_id, override_text=text))
        return True

    def _do_paste(self, clip, clip_id, target_format="", transform="", override_text=None):
        self._put_on_clipboard(clip, target_format, transform, override_text)
        storage.mark_used(clip_id)
        self._deliver_paste()

    def _deliver_paste(self):
        if self.config.get("paste", {}).get("hide_after_paste", True):
            self.hide()
        paster.paste_into(
            CTX.get("last_target_hwnd", 0),
            restore_focus=self.config.get("paste", {}).get("restore_focus", True),
        )

    # -- snippets / templates / import / sync -------------------------------
    def create_snippet(self, name: str, content: str) -> int:
        return storage.create_snippet(name, content)

    def resolve_token(self, name: str) -> dict:
        return templates.resolve_token(name)

    def update_clip_text(self, clip_id: int, content: str) -> None:
        storage.update_content(clip_id, content)

    def clipangel_default_path(self) -> str:
        return importers.default_db_path() or ""

    def import_clipangel(self, path: str, favorites_only: bool = False) -> dict:
        return importers.import_clipangel(path, favorites_only)

    def sync_export(self) -> dict:
        return sync.export_to(self.config.get("sync", {}).get("folder", ""))

    def sync_import(self) -> dict:
        return sync.import_from(self.config.get("sync", {}).get("folder", ""))

    # -- auto-update --------------------------------------------------------
    def check_update(self) -> dict:
        return updater.check(self.config.get("update", {}).get("repo", ""))

    def install_update(self, url: str) -> dict:
        st = updater.stage(url)
        if not st.get("ok"):
            return st
        applied = updater.apply(st["staged"])
        if applied.get("ok"):
            quit_fn = CTX.get("quit")
            if callable(quit_fn):
                quit_fn()
        return applied

    # -- window / config ----------------------------------------------------
    def hide(self) -> None:
        win = _window()
        if win:
            try:
                win.hide()
            except Exception:
                pass

    def _own_hwnd(self) -> int:
        return source_app.get_own_hwnd(os.getpid(), "Lord of the Clipboard")

    def apply_topmost(self) -> None:
        paster.set_topmost(self._own_hwnd(), CTX.get("on_top", True))

    def toggle_on_top(self) -> bool:
        """Flip always-on-top via native SetWindowPos (never pywebview's window)."""
        CTX["on_top"] = not CTX.get("on_top", True)
        _async(self.apply_topmost)
        self.config.setdefault("ui", {})["always_on_top"] = CTX["on_top"]
        cfg.save(self.config)
        return CTX["on_top"]

    def opened_in_favorites_mode(self) -> bool:
        v = CTX.get("favorites_mode", False)
        CTX["favorites_mode"] = False
        return v

    def get_config(self) -> dict:
        return self.config

    def save_config(self, new_cfg: dict) -> dict:
        self.config.clear()
        self.config.update(new_cfg)
        cfg.save(self.config)
        rebind = CTX.get("rebind")
        if callable(rebind):
            rebind()
        return self.config

    def transforms(self) -> list[str]:
        return list(paster.TRANSFORMS.keys())

    def version(self) -> str:
        return __version__
