"""Legend and abbreviation parsing -- the Documents agent's structured half.

A drawing set's legend sheet carries two useful blocks: a symbol legend
(a drawn glyph beside a description) and an abbreviations list (a short
code beside its expansion). The symbol half is a picture and needs vision
to read; the abbreviations half is already text, laid out as a key on one
line and its expansion on the next, and that half is parseable today.

This is deliberately the text half only. Reading the drawn symbol legend
is a vision problem and stays out of the basic version (spec 11.6).

Why it matters: Classification currently receives one concatenated blob
and has to re-derive structure from it on every call. A typed row is the
handoff the architecture asks for -- and it is what lets a downstream
agent say "WP is an abbreviation, so it modifies a device rather than
being one" from data rather than from a model's recollection.
"""

from __future__ import annotations

import re

from .contracts import LegendEntry

# An abbreviation key: short, uppercase, possibly carrying the punctuation
# a drafter uses (C. for conduit, (E) for existing, C.O. for conduit only).
KEY = re.compile(r"^[A-Z][A-Z0-9./()\-]{0,5}$")

# An expansion is words, not a number or a callout. Requiring a run of
# three or more letters admits real single-word expansions (CIRCUIT,
# WEATHERPROOF) while rejecting the coincidental pairings a flat
# key-line/next-line scan otherwise invents on a drawing sheet -- a
# detail bubble followed by its number ("J" then "1"), a grid letter
# followed by a room name.
_WORDY = re.compile(r"[A-Za-z]{3,}")


def _is_expansion(line: str) -> bool:
    return bool(_WORDY.search(line)) and not KEY.match(line)


def parse_legend(schedule_text: str) -> list[LegendEntry]:
    """Key-on-one-line, expansion-on-the-next pairs, in order. The first
    definition of a key wins: a legend sheet repeats headers, and a later
    accidental match must not overwrite a real definition."""
    lines = [l.strip() for l in (schedule_text or "").splitlines() if l.strip()]
    seen: dict[str, LegendEntry] = {}
    for key, expansion in zip(lines, lines[1:]):
        if KEY.match(key) and _is_expansion(expansion) and key not in seen:
            seen[key] = LegendEntry(symbol=key, description=expansion, kind="abbreviation")
    return list(seen.values())
