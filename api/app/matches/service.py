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

# Shared between accept() and discard() rather than typed twice -- both
# raise the exact same refusal for the exact same reason (the match was
# already resolved one way or the other), so one literal keeps the two
# call sites from drifting apart under a future copy edit.
_MATCH_RESOLVED_MESSAGE = "This search has already been added or discarded. Draw a new box to search again."


def load_match(match_id: uuid.UUID, db: DbSession, user: User) -> SymbolMatch:
    match = db.get(SymbolMatch, match_id)
    if match is None:
        raise not_found()
    load_project(match.project_id, db, user)   # the one tenancy gate
    return match


def _lock_match(db: DbSession, match_id: uuid.UUID) -> SymbolMatch:
    """Re-read the match row under `FOR UPDATE` with a fresh view of the
    row, before any `resolved_at`/`status` check -- same reasoning as
    `takeoff.concurrency.lock_item`. Without this, two concurrent
    accepts (a double-click, or two reviewers) both read `resolved_at`
    as `None`, both pass the check, and both call `review.add_item`,
    doubling the drawer's quantity silently -- the second writer's
    `UPDATE ... SET resolved_at = ...` would still land, so nothing
    downstream would even see a conflict to complain about. The lock
    forces the second caller to wait for the first transaction to
    commit its `resolved_at` write, then see it.

    `load_match` already proved the row exists and belongs to the
    caller's org before this is ever reached, so a missing row here
    would mean a concurrent delete raced this call -- surfaced as the
    same 404 a stale id gets anywhere else, not a bare `NoResultFound`.
    """
    locked = db.execute(
        select(SymbolMatch).where(SymbolMatch.id == match_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if locked is None:
        raise not_found()
    return locked


def _plural(name: str, n: int) -> str:
    """Pluralise `name` for the "Added N <name>s from a drawn symbol"
    label, preserving the name's own case rather than forcing it
    entirely lowercase -- a review finding: `name.lower()` silently
    turned "GFCI receptacle" into "gfci receptacles" in the label,
    destroying an acronym an estimator typed on purpose. Only the
    name's very first character is lowered, to read naturally mid-
    sentence ("Added 3 duplex receptacles..."), and only when the name
    doesn't open with an acronym -- a first word that is itself all
    caps (and more than one letter, so a single capital initial doesn't
    count) is left exactly as written.

    Pluralisation is conservative: a name that already ends in "s" is
    left alone (no double plural), "x"/"ch"/"sh" get "es" ("Junction
    box" -> "Junction boxes", "Light switch" -> "Light switches"), a
    consonant followed by "y" gets "y" swapped for "ies" ("Assembly" ->
    "Assemblies"), and everything else just gets "s". `n == 1` returns
    the case-adjusted singular, untouched.
    """
    first_word = name.split(" ", 1)[0]
    is_acronym_led = len(first_word) > 1 and first_word.isupper()
    base = name if is_acronym_led or not name else name[0].lower() + name[1:]
    if n == 1:
        return base
    lowered = base.lower()
    if lowered.endswith("s"):
        return base
    if lowered.endswith(("x", "ch", "sh")):
        return base + "es"
    if len(base) >= 2 and lowered[-1] == "y" and lowered[-2] not in "aeiou":
        return base[:-1] + "ies"
    return base + "s"


def create(db: DbSession, actor: User, sheet: Sheet, box: list[int]) -> SymbolMatch:
    # PAGE_GONE is the sentinel merge.drop_sheets() writes to
    # sheet.unreadable_reason when an approved (or match-sourced) item
    # keeps an otherwise-vanished sheet alive -- a copy edit to that
    # string has to change both call sites, or this check silently stops
    # recognising the condition it exists to catch.
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
    match = _lock_match(db, match.id)
    if match.resolved_at is not None:
        raise DomainError("match_resolved", _MATCH_RESOLVED_MESSAGE, status=409)
    if match.status != "found":
        raise DomainError("match_not_ready", "The search hasn't finished yet. Wait for it to finish, then add the result.", status=409)
    if len(match.matches) == 0:
        raise DomainError("match_empty", "Nothing was found to add. Draw the box again.", status=409)
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
    match = _lock_match(db, match.id)
    if match.resolved_at is not None:
        raise DomainError("match_resolved", _MATCH_RESOLVED_MESSAGE, status=409)
    actions.commit(db, actor=actor, project_id=match.project_id, kind="match_discard",
                   label="Discarded a symbol search", before={"box": match.box}, after={}, sheet_id=match.sheet_id)
    db.delete(match)
    db.flush()
