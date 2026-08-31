"""notes.py -- the note record's service layer.

Every write goes through actions.commit() rather than a bare db.add(),
so a note gets the same attribution and the same append-only audit trail
an approval gets. A note changes what a bid is built on; it is not a
lesser kind of record than an item.

It does NOT get the undo stack. `note_add`/`note_edit`/`note_delete`/
`note_apply` are deliberately absent from `undo.REVERSIBLE`, so undo
walks straight past a note action to the previous reversible one. That
is the safe behaviour -- reversing a note deletion would mean
resurrecting a row from a snapshot, which is its own feature -- but it
means deleting a note is final, which is why the screen confirms first
and says so.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff import actions
from app.takeoff.models import Note, Project

_TRACKED = (
    "scope", "scope_ref", "title", "body", "category", "status",
    "rfi_needed", "usage", "source_ref", "obsolete_after_revision",
)


def list_notes(db: DbSession, project_id: uuid.UUID) -> list[Note]:
    return list(
        db.scalars(select(Note).where(Note.project_id == project_id).order_by(Note.created_at.desc()))
    )


def _snapshot(note: Note) -> dict:
    return {f: getattr(note, f) for f in _TRACKED}


def create_note(db: DbSession, *, actor: User, project: Project, fields: dict) -> Note:
    note = Note(id=uuid.uuid4(), project_id=project.id, author_user_id=actor.id, **fields)
    db.add(note)
    db.flush()
    actions.commit(
        db, actor=actor, project_id=project.id, kind="note_add",
        label=f"Added note: {note.title}", before={}, after=_snapshot(note),
    )
    return note


def update_note(db: DbSession, *, actor: User, project: Project, note: Note, changes: dict) -> Note:
    before = _snapshot(note)
    for key, value in changes.items():
        setattr(note, key, value)
    db.flush()
    actions.commit(
        db, actor=actor, project_id=project.id, kind="note_edit",
        label=f"Edited note: {note.title}", before=before, after=_snapshot(note),
    )
    return note


def delete_note(db: DbSession, *, actor: User, project: Project, note: Note) -> None:
    before = _snapshot(note)
    title = note.title
    db.delete(note)
    db.flush()
    actions.commit(
        db, actor=actor, project_id=project.id, kind="note_delete",
        label=f"Deleted note: {title}", before=before, after={},
    )


def mark_applied(db: DbSession, notes: list[Note]) -> None:
    """Stamped when a re-run has actually carried these notes into the
    takeoff, so the apply banner stops offering work already done."""
    now = datetime.now(timezone.utc)
    for note in notes:
        note.applied_at = now
