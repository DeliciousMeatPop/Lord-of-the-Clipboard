"""Snippet template tokens.

Tokens are written {like_this} inside a snippet. Three kinds:

  * Dynamic values — {date}, {time}, {datetime}, {clipboard}, {clip} — resolve
    to a single value with no prompting.
  * Source tokens — {telegram}, {app:telegram}, {site:steamdb.info} — resolve to
    clips captured from that app/site. The newest is the default, but the caller
    gets the full candidate list so the user can pick an older one.
  * Anything else — a plain fill-in placeholder the UI prompts for.

The UI calls resolve_token() for each token and decides how to fill it.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from . import paster, storage

_DYNAMIC = {"date", "time", "datetime", "clipboard", "clip"}


def _now(fmt: str) -> str:
    return _dt.datetime.now().strftime(fmt)


def dynamic_value(name: str) -> str:
    n = name.lower()
    if n == "date":
        return _now("%Y-%m-%d")
    if n == "time":
        return _now("%H:%M")
    if n == "datetime":
        return _now("%Y-%m-%d %H:%M")
    if n in ("clipboard", "clip"):
        data = paster.read()
        return data.text if (data and data.type == "text") else ""
    return ""


def _slim(c: dict) -> dict[str, Any]:
    return {
        "id": c["id"],
        "content": c["content"],
        "preview": c.get("preview") or (c.get("content") or "")[:120],
        "source_app": c.get("source_app"),
        "source_domain": c.get("source_domain"),
        "created_at": c.get("created_at"),
        "last_used_at": c.get("last_used_at"),
    }


def resolve_token(name: str) -> dict[str, Any]:
    """Return how to fill a token.

    -> {"kind": "value", "value": "..."}                     dynamic, or an
                                                             indexed source pick
    -> {"kind": "source", "term": t, "candidates": [ ... ]}   pick from clips
    -> {"kind": "ask"}                                        prompt the user

    Source tokens accept a trailing :N to grab the Nth-newest directly, e.g.
    {telegram:2}, {app:telegram:2}, {site:steamdb.info:3}.
    """
    raw = (name or "").strip()
    low = raw.lower()
    if low in _DYNAMIC:
        return {"kind": "value", "value": dynamic_value(low)}

    parts = raw.split(":")
    index = None
    if len(parts) > 1 and parts[-1].strip().isdigit():
        index = int(parts.pop().strip())
    if parts and parts[0].lower() in ("app", "site", "source", "from"):
        parts = parts[1:]
    term = ":".join(parts).strip()
    if not term:
        return {"kind": "ask"}

    cands = storage.clips_from_source(term)
    if not cands:
        return {"kind": "ask"}
    if index is not None:
        i = max(1, min(index, len(cands))) - 1   # clamp to range, 1-based
        return {"kind": "value", "value": cands[i]["content"]}
    return {"kind": "source", "term": term, "candidates": [_slim(c) for c in cands]}
