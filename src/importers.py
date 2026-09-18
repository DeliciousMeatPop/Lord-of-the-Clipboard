"""Import history from ClipAngel's SQLite database.

ClipAngel's schema has shifted across versions, so rather than hard-code column
names we introspect the DB: find the table that looks like the clip store, then
map its text/app/title/time/favorite columns by best-effort name matching. Only
text clips are imported (images/files live outside its DB as blobs we skip).
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional

from . import storage

# Common ClipAngel locations (relative to the user profile).
_DEFAULT_RELPATHS = [
    r"AppData\Roaming\ClipAngel\ClipAngel.db",
    r"AppData\Roaming\ClipAngel\clipangel.db",
    r"AppData\Local\ClipAngel\ClipAngel.db",
]

_TEXT_COLS  = ("text", "clip_text", "cliptext", "data", "content", "value")
_APP_COLS   = ("application", "app", "appname", "app_name", "process")
_TITLE_COLS = ("title", "window", "window_title", "caption")
_TIME_COLS  = ("time", "created", "created_at", "date", "timestamp", "moment")
_FAV_COLS   = ("favorite", "favourite", "starred", "pinned")


def default_db_path() -> Optional[str]:
    home = os.path.expanduser("~")
    for rel in _DEFAULT_RELPATHS:
        p = os.path.join(home, rel)
        if os.path.exists(p):
            return p
    return None


def _pick(cols: list[str], candidates) -> Optional[str]:
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in low:
            return low[cand]
    # fuzzy: any column containing the candidate
    for cand in candidates:
        for lc, orig in low.items():
            if cand in lc:
                return orig
    return None


def preview_import(db_path: str) -> dict:
    """Report what would be imported without writing anything."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        best = None
        for t in tables:
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info('{t}')").fetchall()]
            if _pick(cols, _TEXT_COLS):
                n = conn.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
                if best is None or n > best[2]:
                    best = (t, cols, n)
        if not best:
            return {"ok": False, "error": "No clip-like table found in that database."}
        return {"ok": True, "table": best[0], "count": best[2]}
    finally:
        conn.close()


def import_clipangel(db_path: str, favorites_only: bool = False, limit: int = 100000) -> dict:
    info = preview_import(db_path)
    if not info.get("ok"):
        return info
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    imported = 0
    try:
        table = info["table"]
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info('{table}')").fetchall()]
        tc = _pick(cols, _TEXT_COLS)
        ac, ttl, tmc, fc = (_pick(cols, _APP_COLS), _pick(cols, _TITLE_COLS),
                            _pick(cols, _TIME_COLS), _pick(cols, _FAV_COLS))
        rows = conn.execute(f"SELECT * FROM '{table}' LIMIT ?", (limit,)).fetchall()
        colidx = {c: i for i, c in enumerate(cols)}
        for r in rows:
            text = r[colidx[tc]]
            if not isinstance(text, str) or not text.strip():
                continue
            fav = bool(r[colidx[fc]]) if fc else False
            if favorites_only and not fav:
                continue
            cid = storage.add_clip(
                type_="text", content=text, preview=text[:400],
                source_app=(r[colidx[ac]] if ac else "") or "",
                source_title=(r[colidx[ttl]] if ttl else "") or "",
                dedupe_consecutive=False,
            )
            if cid and fav:
                storage.toggle_favorite(cid)
            if cid:
                imported += 1
    except Exception as e:
        return {"ok": False, "error": str(e), "imported": imported}
    finally:
        conn.close()
    return {"ok": True, "imported": imported}
