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

import logging
import re
from dataclasses import dataclass

from . import llm
from .contracts import Proposal

logger = logging.getLogger(__name__)

INTENTS = ("reclassify", "exclude", "set_context", "decide_scope", "decide_plan", "unknown")

_EXCLUDE = ("ignore", "is existing", "existing to remain", "not in contract",
            "not doing", "exclude", "out of scope", "by others",
            # A shape Counting clustered that turns out not to be a device
            # at all -- a room-name label, a grid bubble, a revision cloud
            # -- reads as the same "take this out of the takeoff" request
            # as a scope exclusion, so it routes the same way.
            "not a device")
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


TARGET_FORMS = ("selection", "view", "tag", "record", "none")

# Intents that name one record the screen is already showing. Their key
# must appear in the screen descriptor's own list, so a sentence -- or a
# drawing's text -- cannot reach a record that is not in front of the
# estimator.
_RECORD_INTENTS = ("decide_scope", "decide_plan")

# A decide_* intent settles a record two ways: the decision word itself
# (field "status"), or a rewording of it (field "text"). Anything else --
# a missing field, an empty value, a word outside this set -- is not a
# decision this agent can hand off, so it becomes "unknown" rather than
# a half-formed one propose.py has to guess at.
_DECISION_WORDS = ("confirmed", "dismissed", "found")


@dataclass(frozen=True)
class RouteTargets:
    form: str
    tag: str = ""
    record_key: str = ""


@dataclass(frozen=True)
class Route:
    """What the panel's sentence asked for: an intent, which set it
    applies to, and the estimator's own words where the change records
    them. Never item ids -- the caller resolves the set."""

    intent: str
    targets: RouteTargets
    field: str
    value: str


_UNKNOWN = Route(intent="unknown", targets=RouteTargets(form="none"), field="", value="")


def _screen_line(screen: dict) -> str:
    parts = [f"screen {screen.get('name', '')}"]
    for key in ("sheet", "selection", "filter"):
        if screen.get(key):
            parts.append(f"{key} {screen[key]}")
    records = screen.get("records") or []
    if records:
        parts.append("records on screen: " + ", ".join(records[:40]))
    return "; ".join(parts)


def _from_keywords(message: str, screen: dict) -> Route:
    """The deterministic path, reusing route()'s own needles so the two
    never drift. Only the three intents it can recognise; a record
    decision needs a key and this path has no way to pick one."""
    text = (message or "").strip().lower()
    if _match(text, _EXCLUDE):
        return Route("exclude", RouteTargets(form="selection"), "status", "")
    if _match(text, _RECLASSIFY):
        return Route("reclassify", RouteTargets(form="selection"), "classification", "")
    if _match(text, _CONTEXT):
        return Route("set_context", RouteTargets(form="none"), "text", (message or "").strip())
    return _UNKNOWN


def _validate(raw, message: str, screen: dict) -> Route:
    if not isinstance(raw, dict):
        return _UNKNOWN
    intent = raw.get("intent")
    form = raw.get("target_form")
    if intent not in INTENTS or form not in TARGET_FORMS or intent == "unknown":
        return _UNKNOWN
    field = raw.get("field") if raw.get("field") in ("classification", "status", "text", "") else ""
    value = str(raw.get("value") or "")[:2000]
    tag = str(raw.get("tag") or "")[:50]
    key = str(raw.get("record_key") or "")[:300]
    if intent in _RECORD_INTENTS:
        # The key must be one the screen put in front of the estimator.
        if form != "record" or key not in (screen.get("records") or []):
            return _UNKNOWN
        # And the field/value pair must actually settle it: the decision
        # word itself, or a non-empty rewording -- never both blank, and
        # never a word that is not one of the three decisions.
        if field == "status":
            if value not in _DECISION_WORDS:
                return _UNKNOWN
        elif field == "text":
            if not value:
                return _UNKNOWN
        else:
            return _UNKNOWN
    elif form == "record":
        return _UNKNOWN
    if form == "tag" and not tag:
        return _UNKNOWN
    if intent == "set_context" and not value:
        value = (message or "").strip()
    return Route(intent, RouteTargets(form=form, tag=tag, record_key=key), field, value)


def route_message(message: str, *, screen: dict) -> Route:
    """The panel's entry point. A language reading when a key is set,
    the keyword matcher otherwise and whenever the call fails, so the
    panel degrades to fewer proposals rather than to an error.

    Deliberately a sibling of route() rather than a replacement: route()
    takes concrete anchor ids from the item panel, which already knows
    its targets, while the panel knows only what is on screen.
    """
    if not (message or "").strip():
        return _UNKNOWN
    if llm.available():
        try:
            return _validate(llm.route_message(message, _screen_line(screen)), message, screen)
        except Exception as exc:  # noqa: BLE001 -- routing is enrichment; the panel still answered
            logger.warning("message routing unavailable (%s); used keywords", type(exc).__name__)
    return _from_keywords(message, screen)
