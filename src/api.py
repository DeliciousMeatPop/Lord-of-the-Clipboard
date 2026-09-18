"""The bridge exposed to the web UI as `window.pywebview.api.*`.

Every method here is callable from JavaScript and returns JSON-serialisable
data. The app wires in the live window, config, and monitor after construction.
"""
from __future__ import annotations

import base64
from typing import Any, Optional

from . import config as cfg
from . import importers, markup, paster, storage, sync
from .paths import DATA_DIR


class Api:
    def __init__(self, config: dict):
        self.config = config
        self.window = None                 # set by app after window creation
        self.monitor = None                # set by app; used to skip self-writes
        self.last_target_hwnd = 0          # app the window was summoned from
        self._favorites_mode = False       # did we open via the favorites hotkey?

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

        rows = self.list_clips({**(opts or {}), "sort": "created", "limit": (opts or {}).get("limit", 1000)})
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
        """What the text would look like pasted as `target` — for the menu/preview."""
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
        if self.monitor:
            self.monitor.note_self_write()

    def copy_clip(self, clip_id: int, target_format: str = "", transform: str = "") -> bool:
        """Put a clip on the clipboard without pasting (and mark it used → top)."""
        clip = storage.get_clip(clip_id)
        if not clip:
            return False
        self._put_on_clipboard(clip, target_format, transform)
        storage.mark_used(clip_id)
        return True

    def paste_clip(self, clip_id: int, target_format: str = "", transform: str = "") -> bool:
        """Copy the clip (optionally reformatted/transformed) then paste into the summoning app."""
        clip = storage.get_clip(clip_id)
        if not clip:
            return False
        self._put_on_clipboard(clip, target_format, transform)
        return self._finish_paste(clip_id)

    def paste_snippet(self, clip_id: int, values: dict = None) -> bool:
        """Fill {placeholders} in a snippet and paste the result."""
        clip = storage.get_clip(clip_id)
        if not clip:
            return False
        text = clip.get("content") or ""
        for key, val in (values or {}).items():
            text = text.replace("{" + key + "}", val)
        self._put_on_clipboard(clip, override_text=text)
        return self._finish_paste(clip_id)

    def _finish_paste(self, clip_id: int) -> bool:
        storage.mark_used(clip_id)
        if self.config.get("paste", {}).get("hide_after_paste", True):
            self.hide()
        paster.paste_into(
            self.last_target_hwnd,
            restore_focus=self.config.get("paste", {}).get("restore_focus", True),
        )
        return True

    # -- snippets / import / sync -------------------------------------------
    def create_snippet(self, name: str, content: str) -> int:
        return storage.create_snippet(name, content)

    def update_clip_text(self, clip_id: int, content: str) -> None:
        """Edit a snippet/clip's text in place (re-encrypting if needed)."""
        clip = storage.get_clip(clip_id)
        if not clip:
            return
        storage.delete_clip(clip_id)
        if clip.get("is_snippet"):
            storage.create_snippet(clip.get("name") or "snippet", content)

    def clipangel_default_path(self) -> str:
        return importers.default_db_path() or ""

    def import_clipangel(self, path: str, favorites_only: bool = False) -> dict:
        return importers.import_clipangel(path, favorites_only)

    def sync_export(self) -> dict:
        return sync.export_to(self.config.get("sync", {}).get("folder", ""))

    def sync_import(self) -> dict:
        return sync.import_from(self.config.get("sync", {}).get("folder", ""))

    # -- window / config ----------------------------------------------------
    def hide(self) -> None:
        if self.window:
            try:
                self.window.hide()
            except Exception:
                pass

    def opened_in_favorites_mode(self) -> bool:
        v, self._favorites_mode = self._favorites_mode, False
        return v

    def get_config(self) -> dict:
        return self.config

    def save_config(self, new_cfg: dict) -> dict:
        self.config.clear()
        self.config.update(new_cfg)
        cfg.save(self.config)
        # Re-register hotkeys live if the app provided a rebinder.
        rebind = getattr(self, "rebind_hotkeys", None)
        if callable(rebind):
            rebind()
        return self.config

    def transforms(self) -> list[str]:
        return list(paster.TRANSFORMS.keys())
