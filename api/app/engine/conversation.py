"""Conversation agent (v1, deterministic).

Resolves what an estimator meant into a typed Proposal: which items, which
field, what value. It routes; the owning agent does the work. Given "these
six are all type F", Conversation resolves *which six* and *which field*,
and Classification produces the label -- it never classifies itself,
because two paths to a classification means two classifiers that drift
(design spec 2.5).

Three limits hold here and are covered by tests:

1. It routes, it does not answer. No catalog lookup lives in this module.
2. It proposes, it never writes. Nothing here imports a database session;
   a person applies a proposal through the same path a manual edit takes.
3. Its output is shape-constrained. `intent` comes from INTENTS and
   nothing else, so an unrecognised utterance becomes "unknown" rather
   than an invented action. Conversation is the only agent reading both
   estimator text and extracted drawing text, so this is the surface
   ROADMAP invariant 11 was written for.

v1 matches phrasing deterministically. A language version replaces
`route()` behind this same signature without changing anything downstream.
"""

from __future__ import annotations

import re

from .contracts import Proposal

INTENTS = ("reclassify", "exclude", "set_context", "unknown")

_EXCLUDE = ("ignore", "is existing", "existing to remain", "not in contract",
            "not doing", "exclude", "out of scope", "by others")
_RECLASSIFY = ("are all", "is a", "are type", "all type", "these are", "should be")
_CONTEXT = ("ceiling", "feet", "height", "mounting", "voltage", "in here")


def _match(text: str, needles: tuple[str, ...]) -> bool:
    """Word-boundary matching, not substring. An unanchored `"is a" in text`
    fires inside "th-is a-rea", which routed "the ceiling in this area is 14
    feet" -- a near-verbatim rewording of the design spec's own worked
    example -- to reclassify instead of set_context. Routing is this agent's
    only job, so a phrase must match as words or not at all."""
    return any(re.search(rf"\b{re.escape(n)}\b", text) for n in needles)


def route(message: str, anchor_item_ids: list[str]) -> Proposal:
    """One utterance plus what it was anchored to, resolved into a
    proposal for a person to apply. Never returns None: an unreadable
    message is an explicit "unknown" proposal, not a silent drop."""
    text = (message or "").strip().lower()
    targets = list(anchor_item_ids or [])

    # Exclusion is checked first: "ignore these, they're type F" is a scope
    # exclusion that happens to name a type, not a reclassification.
    #
    # The needle is "is existing", not a bare "existing": on a drawing set
    # an estimator saying an area "is existing" is excluding it, and
    # without any needle for that phrasing word-boundary matching routes
    # "this area is existing" to unknown. But a bare "existing" is a
    # modifier that appears in sentences meaning the opposite -- "replace
    # the existing panel" is scope being *added*, and "these are all type
    # F in the existing wing" is a reclassification -- and because
    # _EXCLUDE is tested first, both were captured as exclusions. The
    # predicate an estimator actually uses to exclude is "is existing";
    # "existing" as an adjective in front of a noun is not one.
    if _match(text, _EXCLUDE):
        return Proposal(intent="exclude", target_item_ids=targets, field="status",
                        value="rejected",
                        summary=f"Exclude {len(targets)} item(s) from the takeoff")
    if _match(text, _RECLASSIFY):
        return Proposal(intent="reclassify", target_item_ids=targets, field="name", value="",
                        summary=f"Reclassify {len(targets)} item(s) — Classification supplies the label")
    if _match(text, _CONTEXT):
        return Proposal(intent="set_context", target_item_ids=targets, field="project_context",
                        value=message.strip(),
                        summary="Record project context from the estimator")
    return Proposal(intent="unknown", target_item_ids=targets, field="", value="",
                    summary="Could not resolve this to a change — ask for specifics")
