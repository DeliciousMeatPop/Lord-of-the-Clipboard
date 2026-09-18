"""Content classification + secret detection.

`content_type()` labels a text clip (url / email / color / phone / code / json /
number / path / text) so the UI can tag and filter it. `looks_secret()` is a
heuristic used by the privacy layer to auto-expire things that smell like
passwords, API keys or card numbers.

Everything is stdlib regex — cheap enough to run on every captured clip.
"""
from __future__ import annotations

import re

_URL     = re.compile(r"^\s*https?://\S+\s*$", re.I)
_EMAIL   = re.compile(r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$")
_HEXCOLOR = re.compile(r"^\s*#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})\s*$", re.I)
_PHONE   = re.compile(r"^\s*\+?[\d][\d\s().-]{6,}\d\s*$")
_NUMBER  = re.compile(r"^\s*-?\d[\d,]*(?:\.\d+)?\s*$")
_WINPATH = re.compile(r"^\s*[a-zA-Z]:\\|^\s*\\\\", re.I)
_CODEISH = re.compile(r"[;{}]\s*$|^\s*(def|class|function|import|const|let|var|public|private|#include|SELECT|<\?php)\b", re.M)

# Secret-ish: long high-entropy tokens, common key prefixes, or card-like digits.
_KEY_PREFIX = re.compile(r"\b(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_\-]{20,})")
_LONG_TOKEN = re.compile(r"^\s*[A-Za-z0-9_\-+/=.]{24,}\s*$")
_CARD       = re.compile(r"^\s*(?:\d[ -]?){13,19}\s*$")


def content_type(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "text"
    if _URL.match(t):
        return "url"
    if _EMAIL.match(t):
        return "email"
    if _HEXCOLOR.match(t):
        return "color"
    if _NUMBER.match(t):
        return "number"
    if _PHONE.match(t) and sum(c.isdigit() for c in t) <= 15:
        return "phone"
    if _WINPATH.match(t):
        return "path"
    stripped = t.lstrip()
    if (stripped.startswith("{") and stripped.rstrip().endswith("}")) or \
       (stripped.startswith("[") and stripped.rstrip().endswith("]")):
        if '"' in t or ":" in t:
            return "json"
    if _CODEISH.search(t):
        return "code"
    return "text"


def looks_secret(text: str) -> bool:
    t = (text or "").strip()
    if not t or "\n" in t:
        return False
    if _KEY_PREFIX.search(t):
        return True
    if _CARD.match(t) and _luhn(re.sub(r"\D", "", t)):
        return True
    if _LONG_TOKEN.match(t) and _entropy(t) > 3.5:
        return True
    return False


def _entropy(s: str) -> float:
    import math
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _luhn(digits: str) -> bool:
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0
