"""Scope statements: the language half of the Documents agent applied to
scope letters, spec sections and general notes. Output is typed records.
Both paths enforce the same rule -- a statement's quote must appear
verbatim in the input, or it is not evidence and is dropped."""
from __future__ import annotations

import logging
import re

from . import llm
from .contracts import ScopeStatement

logger = logging.getLogger(__name__)

KINDS = ("included", "excluded", "by_others", "alternate")
TEXT_MAX, QUOTE_MAX = 500, 600

_HEADINGS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*(EXCLUSIONS?|NOT IN CONTRACT|N\.?I\.?C\.?)\b", re.I), "excluded"),
    (re.compile(r"^\s*BY OTHERS\b", re.I), "by_others"),
    (re.compile(r"^\s*ALTERNATES?\b", re.I), "alternate"),
    (re.compile(r"^\s*(?:SECTION\s+26\s?\d\d\s?\d\d\b.*|INCLUSIONS?|SCOPE(?: OF WORK)?)\b", re.I), "included"),
]
_ALL_CAPS_WORD = re.compile(r"^[A-Z][A-Z&/-]*$")
_BULLET = re.compile(r"^\s*(?:[-•*]|\d+[.)]|[a-z][.)])\s+(.*)$", re.I)


def _kind_of(line: str) -> str | None:
    for pattern, kind in _HEADINGS:
        if pattern.match(line):
            return kind
    return None


def _is_section_break(line: str) -> bool:
    """A *short* all-caps line -- at most four words, no digits or
    trailing punctuation -- reads as a heading (e.g. "GENERAL NOTES")
    and ends whatever block is open. A longer all-caps line under an
    open heading is a shouted sentence (e.g. "PROVIDE TEMPORARY POWER
    BY OTHERS TRADE"), not a new section, and must stay inside the
    block it appears in rather than silently discarding it."""
    words = line.split()
    return 1 <= len(words) <= 4 and all(_ALL_CAPS_WORD.match(w) for w in words)


def extract_deterministic(pages: list[tuple[int, str]]) -> list[ScopeStatement]:
    out: list[ScopeStatement] = []
    for page_index, text in pages:
        kind: str | None = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            k = _kind_of(line)
            if k:
                kind = k
                continue
            if _is_section_break(line):
                kind = None
                continue
            if kind is None:
                continue
            m = _BULLET.match(line)
            body = (m.group(1) if m else line).strip()
            if len(body) < 4:
                continue
            out.append(ScopeStatement(kind=kind, text=body[:TEXT_MAX], quote=raw.strip()[:QUOTE_MAX], page_index=page_index))
    return out


def _validate(raw: list, pages: list[tuple[int, str]]) -> list[ScopeStatement]:
    by_page = {i: t for i, t in pages}
    out = []
    for r in raw or []:
        if not isinstance(r, dict):
            continue
        kind, text, quote = r.get("kind"), str(r.get("text") or "").strip(), str(r.get("quote") or "").strip()
        page_index = r.get("page_index")
        if kind not in KINDS or not text or len(text) > TEXT_MAX or not quote or len(quote) > QUOTE_MAX:
            continue
        if not isinstance(page_index, int) or quote not in by_page.get(page_index, ""):
            continue
        out.append(ScopeStatement(kind=kind, text=text, quote=quote, page_index=page_index))
    return out


def extract(pages: list[tuple[int, str]]) -> list[ScopeStatement]:
    if not any(t.strip() for _, t in pages):
        return []
    if llm.available():
        try:
            joined = "\n\n".join(f"[page {i}]\n{t}" for i, t in pages)
            found = _validate(llm.extract_scope(joined), pages)
            if found:
                return found
        except Exception as exc:  # noqa: BLE001 -- fall back to the headings
            logger.warning("scope extraction unavailable (%s); used headings", type(exc).__name__)
    return extract_deterministic(pages)
