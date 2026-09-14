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

# An abbreviation key: short, uppercase, no trailing dot. The dot is out
# of the character class entirely, which costs the two real abbreviations
# C. and C.O. -- that is the intended trade, because admitting a trailing
# dot admits every sentence-final word in a numbered general-notes block,
# and this set produced BOX., NOTED., OWNER. and REUSE. as keys, each
# paired with the note line following it. Capped at four characters for
# the same reason: APPROX, BUTTON, FEEDER, LEGEND, PANEL and two dozen
# more were parsing as keys off prose.
KEY = re.compile(r"^[A-Z][A-Z0-9/()\-]{0,3}$")

# What cannot be an *expansion* is a separate question from what can be a
# key, and this pattern is deliberately the looser, older key shape.
#
# Tying the two together looks tidy and is wrong: tightening KEY alone
# means every line the tighter pattern stops recognising -- "J-BOX",
# "PMP-3", "M-23" -- becomes eligible as an expansion, and the parser
# invents new pairs faster than the tighter key removes old ones. Measured
# on the real set, sharing one pattern yields 91 keys including five new
# mis-pairings, among them S -> "J-BOX"; S is the switch tag, so that one
# alone would flag every switch on the set for review. Keeping the
# rejection loose yields 86 keys and no new mis-pairings at all.
_NOT_AN_EXPANSION = re.compile(r"^[A-Z][A-Z0-9./()\-]{0,5}$")

# An expansion is words, not a number or a callout. Requiring a run of
# three or more letters admits real single-word expansions (CIRCUIT,
# WEATHERPROOF) while rejecting the coincidental pairings a flat
# key-line/next-line scan otherwise invents on a drawing sheet -- a
# detail bubble followed by its number ("J" then "1"), a grid letter
# followed by a room name.
_WORDY = re.compile(r"[A-Za-z]{3,}")


def _is_expansion(line: str) -> bool:
    return bool(_WORDY.search(line)) and not _NOT_AN_EXPANSION.match(line)


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
