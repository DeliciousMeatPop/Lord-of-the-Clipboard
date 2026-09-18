"""Sync favorites + snippets through a shared folder (Dropbox/OneDrive/etc).

We keep this dead simple and conflict-free: export writes a JSON file of your
favorites and snippets to the configured folder; import merges any entries not
already present (matched by content hash), so pointing two machines at the same
synced folder keeps favorites in step without a server.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from . import storage

FILENAME = "lotc-favorites.json"


def _sig(item: dict) -> str:
    return hashlib.sha256(
        f"{item.get('is_snippet')}\x00{item.get('name') or ''}\x00{item.get('content') or ''}"
        .encode("utf-8", "replace")
    ).hexdigest()


def export_to(folder: str) -> dict:
    if not folder:
        return {"ok": False, "error": "No sync folder configured."}
    try:
        os.makedirs(folder, exist_ok=True)
        favs = storage.list_clips(favorites_only=True, limit=100000)
        snips = storage.list_clips(snippets_only=True, limit=100000)
        payload = {
            "version": 1,
            "exported_at": time.time(),
            "items": [_slim(x) for x in (favs + snips) if x.get("type") == "text"],
        }
        with open(os.path.join(folder, FILENAME), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return {"ok": True, "count": len(payload["items"])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _slim(x: dict) -> dict[str, Any]:
    return {
        "content": x.get("content"),
        "name": x.get("name"),
        "category": x.get("category"),
        "is_snippet": x.get("is_snippet", 0),
        "content_type": x.get("content_type"),
    }


def import_from(folder: str) -> dict:
    if not folder:
        return {"ok": False, "error": "No sync folder configured."}
    path = os.path.join(folder, FILENAME)
    if not os.path.exists(path):
        return {"ok": False, "error": "No sync file found in that folder yet."}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        existing = {
            _sig(x) for x in storage.list_clips(favorites_only=True, limit=100000)
            + storage.list_clips(snippets_only=True, limit=100000)
        }
        added = 0
        for item in payload.get("items", []):
            if _sig(item) in existing:
                continue
            if item.get("is_snippet"):
                storage.create_snippet(item.get("name") or "snippet", item.get("content") or "")
            else:
                cid = storage.add_clip(
                    type_="text", content=item.get("content") or "",
                    preview=(item.get("content") or "")[:400],
                    content_type=item.get("content_type") or "",
                    dedupe_consecutive=False,
                )
                if cid:
                    storage.toggle_favorite(cid)
                    if item.get("category"):
                        storage.set_category(cid, item["category"])
            added += 1
        return {"ok": True, "added": added}
    except Exception as e:
        return {"ok": False, "error": str(e)}
