"""SQLite-backed clipboard history + favorites.

One table, `clips`, holds every captured item. Each connection is created per
call so the store is safe to touch from the monitor thread and the UI thread
without sharing a cursor.

Two timestamps drive the "same post under multiple days" behaviour:
  * created_at    — when it was first copied (its origin day)
  * last_used_at  — when it was last pasted/used (move-to-top day; NULL if never)
The day-grouped view (see api.list_by_day) buckets a clip under BOTH its
copied-day and, when different, its last-used-day.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import Any, Optional

from . import crypto, paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT    NOT NULL,          -- 'text' | 'image' | 'files'
    content       TEXT,                      -- text body, image relpath, or newline-joined file paths
    html          TEXT,                      -- rich CF_HTML fragment when the source provided one
    preview       TEXT,                      -- short text shown in the list
    content_type  TEXT,                      -- auto-tag: url/email/color/code/json/... (text clips)
    source_app    TEXT,                      -- e.g. 'chrome.exe'
    source_title  TEXT,                      -- source window title
    source_exe    TEXT,                      -- full path to the source exe
    source_url    TEXT,                      -- full URL when copied from a browser
    source_domain TEXT,                      -- normalized host, e.g. 'steamdb.info'
    favorite      INTEGER NOT NULL DEFAULT 0,
    is_snippet    INTEGER NOT NULL DEFAULT 0, -- saved reusable snippet (may hold {placeholders})
    name          TEXT,                      -- snippet name
    category      TEXT,
    encrypted     INTEGER NOT NULL DEFAULT 0, -- content/html stored encrypted
    created_at    REAL    NOT NULL,          -- epoch seconds — when first copied
    last_used_at  REAL,                      -- epoch seconds — when last pasted (NULL until used)
    expires_at    REAL,                      -- epoch seconds — auto-delete after (NULL = keep)
    use_count     INTEGER NOT NULL DEFAULT 0,
    hash          TEXT                       -- for consecutive-dedupe
);
CREATE INDEX IF NOT EXISTS idx_clips_created ON clips(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_clips_used    ON clips(last_used_at DESC);
CREATE INDEX IF NOT EXISTS idx_clips_fav     ON clips(favorite);
CREATE INDEX IF NOT EXISTS idx_clips_domain  ON clips(source_domain);
CREATE INDEX IF NOT EXISTS idx_clips_snippet ON clips(is_snippet);
CREATE INDEX IF NOT EXISTS idx_clips_hash    ON clips(hash);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(paths.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _hash(type_: str, content: str) -> str:
    return hashlib.sha256(f"{type_}\x00{content}".encode("utf-8", "replace")).hexdigest()


def latest_hash() -> Optional[str]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT hash FROM clips ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return row["hash"] if row else None


def _decrypt_row(d: dict[str, Any]) -> dict[str, Any]:
    if d and d.get("encrypted"):
        d["content"] = crypto.decrypt(d.get("content") or "")
        if d.get("html"):
            d["html"] = crypto.decrypt(d["html"])
    return d


def add_clip(
    type_: str,
    content: str,
    preview: str,
    html: str = "",
    content_type: str = "",
    source_app: str = "",
    source_title: str = "",
    source_exe: str = "",
    source_url: str = "",
    source_domain: str = "",
    expires_at: Optional[float] = None,
    encrypt: bool = False,
    is_snippet: int = 0,
    name: str = "",
    dedupe_consecutive: bool = True,
) -> Optional[int]:
    """Insert a clip. Returns the new id, or None if it was a consecutive dupe."""
    h = _hash(type_, content)
    if dedupe_consecutive and not is_snippet and latest_hash() == h:
        # Identical to the clip already on top — bump its timestamp instead of duplicating.
        with _connect() as conn:
            conn.execute(
                "UPDATE clips SET created_at = ? WHERE id = "
                "(SELECT id FROM clips ORDER BY created_at DESC LIMIT 1)",
                (time.time(),),
            )
        return None

    enc_flag = 0
    stored_content, stored_html = content, (html or None)
    if encrypt and type_ == "text":
        stored_content, ok1 = crypto.encrypt(content)
        if html:
            stored_html, ok2 = crypto.encrypt(html)
        else:
            ok2 = True
        enc_flag = 1 if (ok1 and ok2) else 0

    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO clips (type, content, html, preview, content_type, source_app, "
            "source_title, source_exe, source_url, source_domain, favorite, is_snippet, "
            "name, encrypted, created_at, expires_at, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (type_, stored_content, stored_html, preview, content_type or None, source_app,
             source_title, source_exe, source_url, source_domain, 1 if is_snippet else 0,
             1 if is_snippet else 0, name or None, enc_flag, time.time(), expires_at, h),
        )
        return cur.lastrowid


def create_snippet(name: str, content: str) -> int:
    """Save a reusable snippet (favorited, may contain {placeholders})."""
    return add_clip(
        type_="text", content=content, preview=content[:400],
        content_type="snippet", is_snippet=1, name=name, dedupe_consecutive=False,
    )


def get_clip(clip_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return _decrypt_row(dict(row)) if row else None


def list_clips(
    query: str = "",
    favorites_only: bool = False,
    snippets_only: bool = False,
    content_type: str = "",
    category: str = "",
    source_app: str = "",
    domain: str = "",
    day: str = "",
    sort: str = "used",
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Flat list with filters.

    sort: 'used'    -> most recently used/copied first (move-to-top behaviour)
          'created' -> most recently copied first
    day:  'YYYY-MM-DD' local date; matches the copied OR last-used date.
    """
    sql = "SELECT * FROM clips WHERE 1=1"
    args: list[Any] = []
    sql += " AND is_snippet = 1" if snippets_only else " AND is_snippet = 0"
    if favorites_only:
        sql += " AND favorite = 1"
    if content_type:
        sql += " AND content_type = ?"
        args.append(content_type)
    if category:
        sql += " AND category = ?"
        args.append(category)
    if source_app:
        sql += " AND source_app = ?"
        args.append(source_app)
    if domain:
        sql += " AND source_domain = ?"
        args.append(domain)
    if day:
        sql += (
            " AND (date(created_at, 'unixepoch', 'localtime') = ?"
            " OR date(last_used_at, 'unixepoch', 'localtime') = ?)"
        )
        args += [day, day]
    if query:
        sql += (" AND (content LIKE ? OR preview LIKE ? OR source_app LIKE ?"
                " OR source_domain LIKE ? OR source_url LIKE ?)")
        like = f"%{query}%"
        args += [like, like, like, like, like]
    order = "COALESCE(last_used_at, created_at) DESC" if sort == "used" else "created_at DESC"
    sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
    args += [limit, offset]
    with _connect() as conn:
        return [_decrypt_row(dict(r)) for r in conn.execute(sql, args).fetchall()]


def mark_used(clip_id: int) -> None:
    """Record that a clip was pasted/used: moves it to top and stamps last_used_at."""
    with _connect() as conn:
        conn.execute(
            "UPDATE clips SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
            (time.time(), clip_id),
        )


def toggle_favorite(clip_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT favorite FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not row:
            return False
        new_val = 0 if row["favorite"] else 1
        conn.execute("UPDATE clips SET favorite = ? WHERE id = ?", (new_val, clip_id))
        return bool(new_val)


def set_category(clip_id: int, category: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE clips SET category = ? WHERE id = ?", (category or None, clip_id))


def delete_clip(clip_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))


def clear_history(keep_favorites: bool = True) -> None:
    with _connect() as conn:
        if keep_favorites:
            conn.execute("DELETE FROM clips WHERE favorite = 0")
        else:
            conn.execute("DELETE FROM clips")


def categories() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM clips WHERE category IS NOT NULL "
            "AND category != '' ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]


def sources() -> dict[str, list[dict[str, Any]]]:
    """Distinct source apps and domains (with counts) for the filter sidebar."""
    with _connect() as conn:
        apps = [
            dict(r) for r in conn.execute(
                "SELECT source_app AS name, COUNT(*) AS n FROM clips "
                "WHERE source_app IS NOT NULL AND source_app != '' "
                "GROUP BY source_app ORDER BY n DESC"
            ).fetchall()
        ]
        domains = [
            dict(r) for r in conn.execute(
                "SELECT source_domain AS name, COUNT(*) AS n FROM clips "
                "WHERE source_domain IS NOT NULL AND source_domain != '' "
                "GROUP BY source_domain ORDER BY n DESC"
            ).fetchall()
        ]
    return {"apps": apps, "domains": domains}


def days() -> list[str]:
    """Distinct local dates on which clips were copied or used, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT d FROM ("
            "  SELECT date(created_at,   'unixepoch', 'localtime') AS d FROM clips WHERE is_snippet = 0"
            "  UNION"
            "  SELECT date(last_used_at, 'unixepoch', 'localtime') AS d FROM clips"
            "  WHERE last_used_at IS NOT NULL AND is_snippet = 0"
            ") WHERE d IS NOT NULL ORDER BY d DESC"
        ).fetchall()
        return [r["d"] for r in rows]


def clips_from_source(term: str, limit: int = 25) -> list[dict[str, Any]]:
    """Text clips whose source app or site matches `term` (newest first).

    Powers snippet tokens like {telegram} / {app:telegram} / {site:steamdb.info}.
    """
    like = f"%{term}%"
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM clips WHERE type = 'text' AND is_snippet = 0 "
            "AND (source_app LIKE ? OR source_domain LIKE ?) "
            "ORDER BY COALESCE(last_used_at, created_at) DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [_decrypt_row(dict(r)) for r in rows]


def content_types() -> list[dict[str, Any]]:
    with _connect() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT content_type AS name, COUNT(*) AS n FROM clips "
                "WHERE is_snippet = 0 AND content_type IS NOT NULL "
                "AND content_type NOT IN ('text','') "
                "GROUP BY content_type ORDER BY n DESC"
            ).fetchall()
        ]


def prune_expired() -> int:
    """Delete clips whose expiry has passed. Returns how many were removed."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM clips WHERE expires_at IS NOT NULL AND expires_at < ? "
            "AND favorite = 0",
            (time.time(),),
        )
        return cur.rowcount


def prune(max_items: int) -> None:
    """Trim non-favorite history down to max_items (favorites never counted/pruned)."""
    if max_items <= 0:
        return
    with _connect() as conn:
        conn.execute(
            "DELETE FROM clips WHERE favorite = 0 AND id NOT IN ("
            "  SELECT id FROM clips WHERE favorite = 0 "
            "  ORDER BY COALESCE(last_used_at, created_at) DESC LIMIT ?"
            ")",
            (max_items,),
        )
