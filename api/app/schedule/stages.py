"""The six stages of electrical work, in the order they run per area
(phasing-research.md §4, §7). A fixed vocabulary, not a table: the
schedule's arithmetic, its undo snapshots, and the client's grid all
index by these keys. Mirrored by src/components/schedule/stages.js.

LONG_LEAD_WORDS is deliberately a subset of market.classify's
QUOTE_REQUIRED_WORDS -- SPDs and VFDs are priced by quote but are not
schedule-driving gear -- plus "panelboard", which the price job treats
as a catalog item. Kept apart so a change here never changes what the
price job does."""
import re

STAGES: tuple[str, ...] = ("demolition", "rough_in", "wire_pull", "gear", "trim", "closeout")

STAGE_LABELS: dict[str, str] = {
    "demolition": "Demolition",
    "rough_in": "Rough-in",
    "wire_pull": "Wire pull",
    "gear": "Gear",
    "trim": "Trim",
    "closeout": "Close-out",
}

# (class key, the words that name it). Order matters: the first class
# whose pattern matches wins, so "switchboard" is tried before the
# looser "switch" would ever be (it is not a word here at all).
LONG_LEAD_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("switchboard", ("switchboard", "switch board")),
    ("switchgear", ("switchgear",)),
    ("mcc", ("mcc", "motor control center")),
    ("transformer", ("transformer",)),
    ("generator", ("generator",)),
    ("ats", ("ats", "automatic transfer")),
    ("busway", ("bus duct", "busway")),
    ("panelboard", ("panelboard", "panel board")),
)

LONG_LEAD_WORDS: tuple[str, ...] = tuple(key for key, _ in LONG_LEAD_CLASSES)


def _pattern(word: str) -> str:
    return re.escape(word) + (r"s?" if " " not in word else "")


_CLASS_RES = tuple(
    (key, re.compile(r"\b(" + "|".join(_pattern(w) for w in words) + r")\b", re.IGNORECASE))
    for key, words in LONG_LEAD_CLASSES
)


def long_lead_class(text: str) -> str | None:
    """The long-lead class an item's name or description names, or None.
    Read-time only -- nothing writes a row because of this."""
    for key, regex in _CLASS_RES:
        if regex.search(text or ""):
            return key
    return None
