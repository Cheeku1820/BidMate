"""Symbol matches: create, read, accept, discard. Accepting is the one
path here that creates an item, and it goes through review.add_item so
the action log, undo, and every status rule see an ordinary item."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.jobs import copy, queue
from app.takeoff import actions, review
from app.takeoff.models import Action, Item, Project, Sheet, SymbolMatch
from app.takeoff.router import load_project, not_found

NOT_SURE_NAME = "Unclassified symbol"


def load_match(match_id: uuid.UUID, db: DbSession, user: User) -> SymbolMatch:
    match = db.get(SymbolMatch, match_id)
    if match is None:
        raise not_found()
    load_project(match.project_id, db, user)   # the one tenancy gate
    return match


def _plural(name: str, n: int) -> str:
    return name.lower() if n == 1 else name.lower() + ("s" if not name.lower().endswith("s") else "")


def create(db: DbSession, actor: User, sheet: Sheet, box: list[int]) -> SymbolMatch:
    if sheet.unreadable_reason == copy.PAGE_GONE:
        raise DomainError("sheet_gone", copy.PAGE_GONE, status=409)
    if not sheet.width_pt or not sheet.height_pt:
        raise DomainError("sheet_still_reading", copy.DRAWINGS_READING, status=409)
    if box[0] - box[2] / 2 < 0 or box[0] + box[2] / 2 > 1000 or box[1] - box[3] / 2 < 0 or box[1] + box[3] / 2 > 750:
        raise DomainError("invalid_box", "Draw the box inside the sheet.", status=422)
    pending = db.scalars(select(SymbolMatch).where(SymbolMatch.sheet_id == sheet.id, SymbolMatch.status == "pending")).first()
    if pending is not None:
        raise DomainError("match_in_progress", "A search is already running on this sheet. Wait for it to finish.", status=409)
    project = db.get(Project, sheet.project_id)
    match = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=list(box), created_by=actor.id)
    db.add(match)
    db.flush()
    queue.enqueue_match(db, match)
    return match


def accept(db: DbSession, actor: User, match: SymbolMatch, *, name: str | None, symbol: str | None, system: str | None,
           not_sure: bool) -> tuple[Item, Action]:
    if match.resolved_at is not None:
        raise DomainError("match_resolved", "This search has already been added or discarded.", status=409)
    if match.status != "found":
        raise DomainError("match_not_ready", "The search hasn't finished yet.", status=409)
    if not not_sure and not (name or "").strip():
        raise DomainError("name_required", "Name the symbol, or choose Not sure yet.", status=422)
    sheet = db.get(Sheet, match.sheet_id)
    project = db.get(Project, match.project_id)
    n = len(match.matches)
    if not_sure:
        warning = {"reason": "legend", "title": "Symbol not in legend",
                   "found": f"A symbol appears {n} times on {sheet.number} but isn't in the legend.",
                   "why": "An unclassified symbol has no catalog item, so it isn't counted or priced yet.",
                   "fix": "Assign a classification, or reject it if it isn't a device.", "where": f"{sheet.number}."}
        item_name, item_symbol, item_system, status = NOT_SURE_NAME, "generic", "Unknown", "attention"
        label = f"Added {n} unclassified symbol{'s' if n != 1 else ''} from a drawn symbol"
    else:
        warning = None
        item_name, item_symbol, item_system, status = name.strip(), symbol or "generic", system or "Unknown", "ready"
        label = f"Added {n} {_plural(item_name, n)} from a drawn symbol"
    item, action = review.add_item(
        db, actor, project=project, sheet=sheet, name=item_name, symbol=item_symbol, system=item_system, quantity=n,
        placements=[list(m) for m in match.matches], x=match.box[0], y=match.box[1],
        source_tag=f"match:{match.id}", status=status, warning=warning, label=label)
    match.resolved_at = datetime.now(timezone.utc)
    db.flush()
    return item, action


def discard(db: DbSession, actor: User, match: SymbolMatch) -> None:
    if match.resolved_at is not None:
        raise DomainError("match_resolved", "This search has already been added or discarded.", status=409)
    actions.commit(db, actor=actor, project_id=match.project_id, kind="match_discard",
                   label="Discarded a symbol search", before={"box": match.box}, after={}, sheet_id=match.sheet_id)
    db.delete(match)
    db.flush()
