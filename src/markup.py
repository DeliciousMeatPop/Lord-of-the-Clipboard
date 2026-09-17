"""On-the-fly markup conversion for the "Paste as ▸" menu.

Two entry points cover the cases:

  * to_markup(clip, target): the main one. If the clip carries rich HTML
    (captured from the source), convert that HTML to the target dialect
    ('markdown' or 'bbcode'). Otherwise treat the plain text as Markdown and
    convert between text dialects.

Targets: 'plain', 'markdown', 'bbcode'. ('rentry' is just Markdown.)

Everything is stdlib (html.parser + re) so there are no extra dependencies.
Converters are deliberately pragmatic — they cover the tags that actually show
up on clipboards (bold/italic/underline/strike, links, code, headings, lists,
blockquotes, paragraphs, line breaks) rather than every HTML edge case.
"""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser


# Per-dialect wrappers for inline styles and structures.
_DIALECTS = {
    "markdown": {
        "b": ("**", "**"), "i": ("*", "*"), "u": ("", ""),          # md has no underline
        "s": ("~~", "~~"), "code": ("`", "`"),
        "h": lambda level, text: f"{'#' * min(level, 6)} {text}",
        "a": lambda text, href: f"[{text}]({href})" if href else text,
        "li_ul": "- ", "li_ol": "{n}. ", "blockquote": "> ",
        "pre": ("```\n", "\n```"),
    },
    "bbcode": {
        "b": ("[b]", "[/b]"), "i": ("[i]", "[/i]"), "u": ("[u]", "[/u]"),
        "s": ("[s]", "[/s]"), "code": ("[code]", "[/code]"),
        "h": lambda level, text: f"[size={200 - level * 20}][b]{text}[/b][/size]",
        "a": lambda text, href: f"[url={href}]{text}[/url]" if href else text,
        "li_ul": "[*] ", "li_ol": "[*] ", "blockquote": "[quote]{text}[/quote]",
        "pre": ("[code]", "[/code]"),
    },
}


class _Converter(HTMLParser):
    def __init__(self, dialect: str):
        super().__init__(convert_charrefs=True)
        self.d = _DIALECTS[dialect]
        self.out: list[str] = []
        self._href = ""
        self._link_text: list[str] = []
        self._in_link = False
        self._ol_counter: list[int] = []
        self._list_stack: list[str] = []  # 'ul' | 'ol'

    # -- helpers ------------------------------------------------------------
    def _emit(self, s: str) -> None:
        (self._link_text if self._in_link else self.out).append(s)

    # -- tags ---------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("b", "strong"):
            self._emit(self.d["b"][0])
        elif tag in ("i", "em"):
            self._emit(self.d["i"][0])
        elif tag == "u":
            self._emit(self.d["u"][0])
        elif tag in ("s", "strike", "del"):
            self._emit(self.d["s"][0])
        elif tag == "code":
            self._emit(self.d["code"][0])
        elif tag == "pre":
            self._emit(self.d["pre"][0])
        elif tag == "a":
            self._in_link = True
            self._link_text = []
            self._href = a.get("href", "")
        elif tag == "br":
            self._emit("\n")
        elif tag in ("p", "div"):
            if self.out and not "".join(self.out).endswith("\n\n"):
                self._emit("\n\n")
        elif tag == "ul":
            self._list_stack.append("ul")
        elif tag == "ol":
            self._list_stack.append("ol")
            self._ol_counter.append(0)
        elif tag == "li":
            kind = self._list_stack[-1] if self._list_stack else "ul"
            self._emit("\n")
            if kind == "ol":
                self._ol_counter[-1] += 1
                self._emit(self.d["li_ol"].replace("{n}", str(self._ol_counter[-1])))
            else:
                self._emit(self.d["li_ul"])
        elif tag == "blockquote":
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag in ("b", "strong"):
            self._emit(self.d["b"][1])
        elif tag in ("i", "em"):
            self._emit(self.d["i"][1])
        elif tag == "u":
            self._emit(self.d["u"][1])
        elif tag in ("s", "strike", "del"):
            self._emit(self.d["s"][1])
        elif tag == "code":
            self._emit(self.d["code"][1])
        elif tag == "pre":
            self._emit(self.d["pre"][1])
        elif tag == "a" and self._in_link:
            self._in_link = False
            text = "".join(self._link_text)
            self.out.append(self.d["a"](text, self._href))
        elif tag in ("p", "div"):
            self._emit("\n")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                popped = self._list_stack.pop()
                if popped == "ol" and self._ol_counter:
                    self._ol_counter.pop()
            self._emit("\n")
        elif tag and tag[0] == "h" and tag[1:].isdigit():
            pass  # handled in data via headings map below

    def handle_data(self, data):
        self._emit(data)

    def result(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)


def _apply_headings(html: str, dialect: str) -> str:
    fn = _DIALECTS[dialect]["h"]

    def repl(m):
        level = int(m.group(1))
        inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        return "\n\n" + fn(level, unescape(inner)) + "\n\n"

    return _HEADING_RE.sub(repl, html)


def html_to(dialect: str, html: str) -> str:
    html = _apply_headings(html, dialect)
    conv = _Converter(dialect)
    conv.feed(html)
    return conv.result()


# --- plain-text (Markdown source) <-> BBCode -------------------------------
_MD_TO_BB = [
    (re.compile(r"\*\*(.+?)\*\*", re.DOTALL), r"[b]\1[/b]"),
    (re.compile(r"__(.+?)__", re.DOTALL), r"[b]\1[/b]"),
    (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.DOTALL), r"[i]\1[/i]"),
    (re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", re.DOTALL), r"[i]\1[/i]"),
    (re.compile(r"~~(.+?)~~", re.DOTALL), r"[s]\1[/s]"),
    (re.compile(r"`([^`]+?)`"), r"[code]\1[/code]"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r"[url=\2]\1[/url]"),
]
_BB_TO_MD = [
    (re.compile(r"\[b\](.+?)\[/b\]", re.DOTALL | re.IGNORECASE), r"**\1**"),
    (re.compile(r"\[i\](.+?)\[/i\]", re.DOTALL | re.IGNORECASE), r"*\1*"),
    (re.compile(r"\[s\](.+?)\[/s\]", re.DOTALL | re.IGNORECASE), r"~~\1~~"),
    (re.compile(r"\[code\](.+?)\[/code\]", re.DOTALL | re.IGNORECASE), r"`\1`"),
    (re.compile(r"\[url=([^\]]+)\](.+?)\[/url\]", re.DOTALL | re.IGNORECASE), r"[\2](\1)"),
    (re.compile(r"\[url\](.+?)\[/url\]", re.DOTALL | re.IGNORECASE), r"\1"),
]


def _sub_all(rules, text: str) -> str:
    for pat, rep in rules:
        text = pat.sub(rep, text)
    return text


def to_markup(clip: dict, target: str) -> str:
    """Render a clip's text into the target markup ('plain'|'markdown'|'bbcode')."""
    html = (clip or {}).get("html") or ""
    text = (clip or {}).get("content") or ""

    if target == "plain":
        return to_plain(clip)

    if html and target in ("markdown", "bbcode"):
        return html_to(target, html)

    # No rich HTML: treat plain text as Markdown and convert dialects.
    if target == "bbcode":
        return _sub_all(_MD_TO_BB, text)
    if target == "markdown":
        # If it looks like BBCode, convert to Markdown; else pass through.
        return _sub_all(_BB_TO_MD, text) if "[/" in text else text
    return text


def to_plain(clip: dict) -> str:
    html = (clip or {}).get("html") or ""
    if html:
        return re.sub(r"\s+\n", "\n", re.sub(r"<[^>]+>", "", unescape(html))).strip()
    return (clip or {}).get("content") or ""
