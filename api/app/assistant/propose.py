"""A routed sentence becomes one typed proposal -- or nothing.

Shape-constrained on purpose (ROADMAP invariant 11): the kind is from a
closed set, each arm carries only the fields its own endpoint takes, and
every id was resolved from the project's rows by `targets.py` or looked
up from a key the screen itself offered. Nothing the model returned
becomes an id.

Nothing here writes. The estimator's press calls the record's own
endpoint -- the same path its form uses.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.assistant import proposal_copy as copy
from app.assistant import targets
from app.assistant.schemas import ScreenIn
from app.engine.conversation import Route
from app.plan import service as plan_service
from app.scope import service as scope_service
from app.takeoff import resolve as resolve_service
from app.takeoff.models import Item, Project, Sheet

PROPOSAL_KINDS = ("item", "note", "scope", "plan_line", "plan_answer", "refused")

# Which screens put records in front of the estimator. A sentence can
# only settle a record the screen it was typed on is showing.
_SCOPE_SCREENS = ("confirm", "plan")
_PLAN_SCREENS = ("plan",)

_PHYSICAL = ("ceiling", "height", "feet", "mounting", "voltage", "existing", "wall", "slab", "conduit")
_DECISIONS = ("confirmed", "dismissed", "found")


def _preview(items: list[Item]) -> tuple[list[dict], int]:
    rows = [{"label": i.name, "detail": f"{i.quantity:g} {i.unit}"} for i in items[:5]]
    return rows, max(0, len(items) - 5)


def record_keys(db: DbSession, project: Project, screen: ScreenIn) -> list[str]:
    """The keys the screen currently offers, in the form the router may
    echo back. A key outside this list is never a target."""
    keys: list[str] = []
    if screen.name in _SCOPE_SCREENS:
        keys += [f"scope:{s.id}" for s in scope_service.list_statements(db, project)]
    if screen.name in _PLAN_SCREENS:
        _docs, _scope, specs, scheds, phases, added, questions = plan_service.derive(db, project)
        keys += [f"plan:{line.key}" for line in (*specs, *scheds, *phases)]
        keys += [f"plan:phase:added:{p.id}" for p in added]
        keys += [f"plan:{q.key}" for q in questions]
    return keys


def _note_from(value: str, message: str) -> dict:
    body = (value or message or "").strip()
    title = (body.split(". ")[0].strip().rstrip(".") or body)[:300]
    lowered = body.lower()
    category = "existing_condition" if any(w in lowered for w in _PHYSICAL) else "customer_instruction"
    return {"kind": "note", "summary": copy.note(title), "title": title, "body": body[:4000],
            "category": category, "usage": "context", "targets_preview": [], "more_count": 0}


def _jsonable(resolved: dict) -> dict:
    """The resolve service returns uuids and a versions map keyed by
    uuid; the wire wants strings. `versions` is what apply-proposal
    checks optimistic concurrency against, so it crosses intact."""
    out = dict(resolved)
    out["target_item_ids"] = [str(i) for i in resolved["target_item_ids"]]
    out["versions"] = {str(k): v for k, v in (resolved.get("versions") or {}).items()}
    return out


def _item_proposal(db, project, route, screen, message):
    rows = targets.resolve_items(db, project, route.targets, screen)
    if not rows:
        return None
    anchor = targets.anchor_of(rows, selected_id=screen.item_id)
    cluster = route.targets.form == "selection"
    resolved = resolve_service.resolve_for_item(db, anchor, message, cluster=cluster)
    if not cluster:
        # The estimator named a set the cluster helper did not pick, so
        # the proposal applies to exactly what was resolved here.
        resolved["target_item_ids"] = [i.id for i in rows]
        resolved["versions"] = {i.id: i.version for i in rows}
    if route.intent == "exclude":
        resolved["intent"] = "exclude"
        resolved["reject_reason"] = message.strip()[:2000]
    count = len(resolved["target_item_ids"])
    sheet = db.get(Sheet, anchor.sheet_id)
    sheet_number = sheet.number if sheet is not None else ""
    summary = (copy.exclude(count, sheet_number) if route.intent == "exclude"
               else copy.reclassify(count, resolved["name"], sheet_number))
    preview, more = _preview(rows)
    return {"kind": "item", "summary": summary, "note": copy.item_note(), "count": count,
            "sheet_number": sheet_number, "item_id": str(anchor.id), "approve": False,
            "proposal": _jsonable(resolved), "targets_preview": preview, "more_count": more}


def _scope_proposal(db, project, route, key):
    statement_id = key.split(":", 1)[1]
    statement = next((s for s in scope_service.list_statements(db, project) if str(s.id) == statement_id), None)
    if statement is None:
        return None
    current = statement.edited_text or statement.text
    out = {"kind": "scope", "statement_id": str(statement.id), "quote": statement.quote,
           "current_text": current, "targets_preview": [], "more_count": 0}
    if route.field == "text" and route.value.strip():
        out["edited_text"] = route.value.strip()[:500]
        out["summary"] = copy.scope_text(out["edited_text"])
        return out
    status = route.value.strip().lower()
    if status not in _DECISIONS:
        return None
    out["status"] = status
    out["summary"] = copy.scope_status(status, current)
    return out


def _plan_proposal(db, project, route, key):
    entry_key = key.split(":", 1)[1]
    _docs, _scope, specs, scheds, phases, added, questions = plan_service.derive(db, project)
    question = next((q for q in questions if q.key == entry_key), None)
    if question is not None:
        body = route.value.strip()
        if not body:
            return None
        return {"kind": "plan_answer", "project_id": str(project.id), "key": entry_key,
                "question_title": question.title, "body": body[:4000],
                "summary": copy.plan_answer(question.title), "targets_preview": [], "more_count": 0}
    line = next((l for l in (*specs, *scheds, *phases) if l.key == entry_key), None)
    current = line.text if line is not None else next(
        (p.name for p in added if f"phase:added:{p.id}" == entry_key), None)
    if current is None:
        return None
    out = {"kind": "plan_line", "project_id": str(project.id), "key": entry_key,
           "current_text": current, "targets_preview": [], "more_count": 0}
    if route.field == "text" and route.value.strip():
        out["edited_text"] = route.value.strip()[:500]
        out["summary"] = copy.plan_text(out["edited_text"])
        return out
    status = route.value.strip().lower()
    if status not in _DECISIONS:
        return None
    out["status"] = status
    out["summary"] = copy.plan_status(status, current)
    return out


def build(db: DbSession, *, project: Project, route: Route, screen: ScreenIn, message: str) -> dict | None:
    """One wire-ready proposal, or None when nothing is proposable. A
    target set past the cap is a refusal the card shows, not an error."""
    if route.intent == "unknown":
        return None
    try:
        if route.intent in ("reclassify", "exclude"):
            return _item_proposal(db, project, route, screen, message)
        if route.intent == "set_context":
            return _note_from(route.value, message)
        key = route.targets.record_key
        if key not in record_keys(db, project, screen):
            return None
        if route.intent == "decide_scope" and key.startswith("scope:"):
            return _scope_proposal(db, project, route, key)
        if route.intent == "decide_plan" and key.startswith("plan:"):
            return _plan_proposal(db, project, route, key)
    except targets.TooMany as many:
        return {"kind": "refused", "summary": copy.too_many(many.count), "targets_preview": [], "more_count": 0}
    return None
