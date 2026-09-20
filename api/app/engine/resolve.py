"""The estimator's sentence -> the fields of a proposal (say-what-it-is
spec, "The resolve service" steps 3-5).

Three pieces, each small enough to test on plain data:

- `candidates()` picks the few catalog and firm-library entries closest
  to the sentence, so the model chooses among things that exist rather
  than the whole list. Token overlap, not embeddings: tens of
  candidates, and it keeps the API free of a second network dependency.
- `typed_fallback()` is what a sentence becomes when no model can read
  it -- no key, a timeout, a malformed answer. The words are the name,
  the item is custom and unpriced, and the estimator still approves.
  This is the structured path CLAUDE.md requires to exist; the model
  only ever improves on it.
- `resolve()` runs the call and falls back. It never raises: the panel
  has no "the engine failed" state, only "read from your words".

Nothing here reads or writes the database, and nothing here decides to
reject -- `conversation.route()` did that before this module is called.
"""
from __future__ import annotations

import logging
import re

from . import llm

logger = logging.getLogger(__name__)

TYPED_SUMMARY = "Read from your words as a custom item."
_REQUIRED = ("name", "system", "category", "unit", "catalog_id", "schedule_match", "quantity", "summary")
_STOP = {"a", "an", "the", "of", "on", "in", "per", "these", "this", "it", "its", "is", "are", "and", "with", "for", "to"}


def leading_count(text: str) -> int | None:
    """An integer the sentence starts with, read as a count -- "28 of
    these ..." -- but not a size like "2x4" or "20A" standing alone as
    the first word. A count may itself be followed by a size ("12 20A
    duplex receptacles" -> 12, "28 2x4 LED troffers" -> 28): what rules
    a token out is being a *plain* number, not merely starting with a
    digit."""
    m = re.match(r"\s*(\d{1,5})(?=\s+(?!\d+(?:\s|$)))", text or "")
    return int(m.group(1)) if m else None


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in _STOP}


def candidates(text: str, catalog: dict, resolutions: list[dict], *, tag_hint: str | None = None, limit: int = 5) -> list[dict]:
    """Up to `limit` entries from the catalog (`{id: CatalogItem}`) and
    the project's resolutions (`[{id, tag, name, system, category}]`),
    ranked by shared words with the sentence. A resolution for the
    item's own tag ranks first regardless -- what this firm already said
    F is beats what the words happen to overlap with."""
    words = _tokens(text)
    scored: list[tuple[float, dict]] = []
    for r in resolutions:
        entry = {"id": r["id"], "name": r["name"], "system": r["system"], "category": r["category"]}
        boost = 100.0 if tag_hint and r.get("tag") == tag_hint else 0.0
        scored.append((boost + len(words & _tokens(r["name"])), entry))
    for cid, c in catalog.items():
        entry = {"id": cid, "name": c.name, "system": c.system, "category": c.category}
        scored.append((float(len(words & _tokens(c.name))), entry))
    scored.sort(key=lambda p: -p[0])
    return [e for score, e in scored[:limit] if score > 0]


def typed_fallback(text: str) -> dict:
    count = leading_count(text)
    original = (text or "").strip()
    name = original
    if count is not None:
        stripped = re.sub(r"^\s*\d{1,5}\s+(of\s+(these|them)\s*,?\s*)?", "", original).strip(" ,")
        # "6 of these" strips to nothing -- the typed path is the floor
        # this feature never falls through, so a nameless record is
        # worse than a redundant one. Keep the original words instead.
        name = stripped or original
    return {
        "name": name, "system": "Unknown", "category": "Unclassified", "unit": "ea",
        "catalog_id": None, "schedule_match": None, "quantity": count,
        "summary": TYPED_SUMMARY, "source": "typed",
    }


def _quantity_is_stated(text: str, quantity: int) -> bool:
    """Whether `quantity` appears in `text` as a whole number, not as a
    substring of a different number or a unit ("500A" does not state
    500). This is what keeps a model-proposed quantity from silently
    coming out of the schedule text instead of the estimator's own
    words -- the rule the prompt asks for, enforced by shape."""
    return re.search(rf"\b{re.escape(str(quantity))}\b", text or "") is not None


def resolve(text: str, item_ctx: dict, candidates_: list[dict], schedule_text: str) -> dict:
    """One Classification call, or the typed fallback. `item_ctx` is
    `{"tag", "count", "sheet"}`."""
    if not llm.available():
        return typed_fallback(text)
    try:
        answer = llm.resolve_proposal(text, item_ctx, candidates_, schedule_text)
        if not isinstance(answer, dict) or any(k not in answer for k in _REQUIRED) or not str(answer.get("name") or "").strip():
            raise ValueError("proposal missing fields")
        out = {k: answer[k] for k in _REQUIRED}
        model_quantity = out["quantity"]
        if model_quantity is not None and _quantity_is_stated(text, int(model_quantity)):
            out["quantity"] = int(model_quantity)
        else:
            out["quantity"] = leading_count(text)
        out["source"] = "read"
        return out
    except Exception as exc:  # noqa: BLE001 -- any failure is the typed path, never a dead end
        logger.warning("resolve unavailable (%s); used the estimator's words", type(exc).__name__)
        return typed_fallback(text)
