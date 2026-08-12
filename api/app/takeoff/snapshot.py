"""The polling payload (`build`) and its version (`version`).

`/snapshot` is the workhorse the review workspace polls every few seconds:
one request returning everything it renders, so the client can diff a
version string against what it last saw and skip the render entirely on a
304. Getting `version()` right matters as much as `build()` -- a version
that changes when nothing did makes the ETag worthless (the client never
gets a 304 and polls at full cost forever); a version that fails to change
when something did means a colleague's approval never appears.

Presence versus the ETag (task-11-brief.md, decision 3): `SnapshotOut`
carries `presence`, but presence updates write no `Action` row, so a
version derived purely from the action log would never change when a
colleague only moves their selection -- the request 304s and remote
selection never updates, which the README demonstrates as a feature.
Recommendation (a) is taken here: `version()` folds in
`app.collab.service.presence_signal()`, a small seam that returns a
constant until Task 12's `Presence` table exists for it to query for real.
See the Task 11 report for the full reasoning.
"""

import hashlib
import uuid
from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.collab.service import active_presence, presence_signal
from app.identity.models import User
from app.takeoff import undo as undo_module
from app.takeoff.models import Action, Item, Sheet, Warning
from app.takeoff.schemas import ItemOut, SheetOut, SnapshotOut, TotalsOut, UndoOut, WarningOut
from app.takeoff.totals import approved_totals


def version(db: DbSession, project_id: uuid.UUID) -> str:
    """A short fingerprint of `project_id`'s current state, for the
    `ETag` / `If-None-Match` cycle.

    Built from `Action.seq`, never `Action.created_at`: `created_at` is the
    *transaction* timestamp, identical for every row a single compound
    action (bulk approval, scale confirmation) writes, so it cannot
    distinguish "one action landed" from "fourteen did" -- exactly why
    `undo.py` already orders by `seq` instead. `seq` is a real Postgres
    `Identity(always=True)` sequence: strictly increasing regardless of
    transaction boundaries or clock resolution, which is what a total
    order over the log actually needs.

    `count` rides alongside `max(seq)` as a cheap extra check: the action
    log is append-only (a database trigger refuses UPDATE/DELETE on
    `actions`), so `count` cannot decrease, but folding it in costs nothing
    and guards against a future append path that somehow reuses a `seq`
    value rather than trusting `max(seq)` alone.
    """
    latest_seq, count = db.execute(
        select(func.max(Action.seq), func.count()).where(Action.project_id == project_id)
    ).one()
    presence = presence_signal(db, project_id)
    raw = f"{project_id}:{latest_seq}:{count}:{presence}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _warning_out(warning: Warning) -> WarningOut:
    return WarningOut(
        title=warning.title,
        found=warning.found,
        why=warning.why,
        fix=warning.fix,
        where=warning.where_,
        reason=warning.reason.value,
    )


def sheet_out(sheet: Sheet) -> SheetOut:
    return SheetOut(
        id=sheet.id,
        number=sheet.number,
        title=sheet.title,
        discipline=sheet.discipline,
        revision=sheet.revision,
        scale=sheet.scale,
        scale_options=sheet.scale_options,
        plan=sheet.plan,
        superseded=sheet.superseded_at is not None,
    )


def _item_out(item: Item, warning: Warning | None, approved_by_name: str | None) -> ItemOut:
    return ItemOut(
        id=item.id,
        sheet_id=item.sheet_id,
        symbol=item.symbol,
        name=item.name,
        description=item.description,
        system=item.system,
        category=item.category,
        quantity=item.quantity,
        unit=item.unit,
        status=item.status.value,
        approved_by=approved_by_name,
        rejected=item.rejected_at is not None,
        x=item.x,
        y=item.y,
        path=item.path,
        notes=item.notes,
        evidence=item.evidence,
        warning=_warning_out(warning) if warning is not None else None,
    )


def build(db: DbSession, actor: User, project_id: uuid.UUID) -> SnapshotOut:
    """Everything the review workspace renders for `project_id`, as of
    right now, on `actor`'s behalf.

    `actor` exists because `undo_head`/`redo_head` authorize internally
    (Task 10) and need someone to authorize -- the router's `load_project`
    gate already refused a cross-org request before this function is ever
    called, so that internal check is defence in depth here, not the
    primary gate.
    """
    sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project_id).order_by(Sheet.sort_order)))
    items = list(db.scalars(select(Item).where(Item.project_id == project_id)))

    # Scoped to this project via a join through Item, not a bare
    # `select(Warning)` over the whole table -- the plan's sketch loaded
    # every warning in the database, across every org, into memory on
    # every poll. Sheet-level warnings (Warning.sheet_id set, item_id
    # null) are out of scope for ItemOut, which only carries per-item
    # warnings; SheetOut has no warning field, matching the plan's schema.
    warnings_by_item_id = {
        w.item_id: w
        for w in db.scalars(
            select(Warning).join(Item, Item.id == Warning.item_id).where(Item.project_id == project_id)
        )
    }

    head = undo_module.undo_head(db, actor, project_id)
    redo_head = undo_module.redo_head(db, actor, project_id)

    # Scoped to exactly the user ids this response actually needs to name
    # -- every item's approver plus whoever performed the undo head's
    # action -- rather than the plan's sketch, which loaded every user in
    # the database, across every org, to build a name lookup for two
    # fields. Implicitly org-scoped too: every id collected here was read
    # off a row already filtered to this project.
    referenced_user_ids = {i.approved_by_user_id for i in items if i.approved_by_user_id is not None}
    if head is not None:
        referenced_user_ids.add(head.actor_user_id)
    names = (
        {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(referenced_user_ids)))}
        if referenced_user_ids
        else {}
    )

    presence = active_presence(db, project_id, exclude=actor.id)

    return SnapshotOut(
        version=version(db, project_id),
        sheets=[sheet_out(s) for s in sheets],
        items=[_item_out(i, warnings_by_item_id.get(i.id), names.get(i.approved_by_user_id)) for i in items],
        totals=TotalsOut(**asdict(approved_totals(db, project_id))),
        undo=UndoOut(
            can_undo=head is not None,
            can_redo=redo_head is not None,
            undo_label=head.label if head is not None else None,
            undo_by=names.get(head.actor_user_id) if head is not None else None,
            redo_label=redo_head.label if redo_head is not None else None,
        ),
        presence=presence,
    )
