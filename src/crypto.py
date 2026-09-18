"""Optional at-rest encryption of clip text.

When enabled (config.privacy.encrypt), clip `content`/`html` are stored
encrypted with a Fernet key kept in a separate file (data/secret.key). This
protects the history if the DB alone is copied or synced without the key file;
it is not protection against a local attacker who has both files.

Degrades safely: if the `cryptography` package or the key is missing, values
are stored as plain text and marked unencrypted.
"""
from __future__ import annotations

from typing import Optional

from .paths import DATA_DIR

_KEY_PATH = DATA_DIR / "secret.key"
_PREFIX = "enc:v1:"

try:
    from cryptography.fernet import Fernet
    _HAVE = True
except BaseException:  # pragma: no cover — a broken native build can panic, not just ImportError
    _HAVE = False

_fernet = None


def available() -> bool:
    return _HAVE


def _load() -> Optional["Fernet"]:
    global _fernet
    if not _HAVE:
        return None
    if _fernet is not None:
        return _fernet
    try:
        if not _KEY_PATH.exists():
            _KEY_PATH.write_bytes(Fernet.generate_key())
            try:
                _KEY_PATH.chmod(0o600)
            except Exception:
                pass
        _fernet = Fernet(_KEY_PATH.read_bytes())
    except Exception:
        _fernet = None
    return _fernet


def encrypt(text: str) -> tuple[str, bool]:
    """Return (stored_value, was_encrypted)."""
    f = _load()
    if not f or text is None:
        return text, False
    try:
        return _PREFIX + f.encrypt(text.encode("utf-8")).decode("ascii"), True
    except Exception:
        return text, False


def decrypt(value: str) -> str:
    if not value or not value.startswith(_PREFIX):
        return value
    f = _load()
    if not f:
        return ""  # can't read without the key
    try:
        return f.decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except Exception:
        return ""
