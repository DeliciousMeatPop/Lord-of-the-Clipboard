"""Background clipboard watcher.

Polls the Windows clipboard sequence number (cheap, robust, no message pump)
and, when it changes, snapshots the content, resolves the source app/site, and
hands the new clip to a callback. Writes we make ourselves (restoring a clip to
paste it) are skipped so they don't pollute history.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Callable, Optional

from . import paster, source_app, storage
from .paths import IMAGES_DIR


def _preview(text: str, limit: int = 400) -> str:
    text = text.strip()
    return text[:limit]


class ClipboardMonitor:
    def __init__(self, config: dict, on_new_clip: Optional[Callable[[dict], None]] = None):
        self.config = config
        self.on_new_clip = on_new_clip
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_seq = paster.sequence_number()
        self._ignore_seq = -1  # sequence number of a write we made ourselves

    # Called by the paste path so our own clipboard writes aren't re-captured.
    def note_self_write(self) -> None:
        self._ignore_seq = paster.sequence_number()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        interval = self.config.get("monitor", {}).get("poll_interval_ms", 400) / 1000.0
        while not self._stop.wait(interval):
            try:
                seq = paster.sequence_number()
                if seq == self._last_seq:
                    continue
                self._last_seq = seq
                if seq == self._ignore_seq:
                    continue  # our own write
                self._capture()
            except Exception:
                # Never let a bad read kill the loop.
                continue

    def _capture(self) -> None:
        mon = self.config.get("monitor", {})
        data = paster.read()
        if data is None:
            return

        # Resolve where it came from *before* anything steals focus.
        src = source_app.capture()
        if src.app and src.app in {a.lower() for a in mon.get("ignore_apps", [])}:
            return  # e.g. password managers

        html = ""
        if data.type == "text":
            if not mon.get("capture_text", True):
                return
            text = data.text
            if len(text) > mon.get("max_text_length", 1_000_000):
                text = text[: mon.get("max_text_length", 1_000_000)]
            content, preview, html = text, _preview(text), data.html
        elif data.type == "image":
            if not mon.get("capture_images", True):
                return
            rel = f"images/{uuid.uuid4().hex}.png"
            try:
                data.image.save(IMAGES_DIR.parent / rel, "PNG")
            except Exception:
                return
            content, preview = rel, "[image]"
        elif data.type == "files":
            if not mon.get("capture_files", True):
                return
            content = "\n".join(data.paths or [])
            preview = f"[{len(data.paths or [])} file(s)] " + ", ".join(
                p.split("\\")[-1] for p in (data.paths or [])[:3]
            )
        else:
            return

        clip_id = storage.add_clip(
            type_=data.type,
            content=content,
            preview=preview,
            html=html,
            source_app=src.app,
            source_title=src.title,
            source_exe=src.exe,
            source_url=src.url,
            source_domain=src.domain,
            dedupe_consecutive=self.config.get("history", {}).get("dedupe_consecutive", True),
        )
        if clip_id is None:
            return

        storage.prune(self.config.get("history", {}).get("max_items", 5000))
        if self.on_new_clip:
            row = storage.get_clip(clip_id)
            if row:
                self.on_new_clip(row)
