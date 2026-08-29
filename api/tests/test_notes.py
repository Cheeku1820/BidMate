"""app/takeoff/models.py's Note -- a structured record of something the
drawings do not say, and the `usage` flag that decides whether it feeds
the engine or is documentation only.
"""
import uuid

import pytest
from sqlalchemy import select

from app.takeoff.models import Item, Note


def test_note_carries_its_scope_and_usage(db, project, dana):
    note = Note(
        project_id=project.id, scope="project", scope_ref=None,
        title="Low-voltage systems excluded from Division 26",
        body="Fire alarm, security, and structured cabling are excluded per the Turner scope letter.",
        category="exclusion", status="confirmed", rfi_needed=False,
        usage="context", source_ref="Turner scope letter", author_user_id=dana.id,
    )
    db.add(note)
    db.flush()
    assert note.scope == "project"
    assert note.usage == "context"
    assert note.applied_at is None
    assert note.created_at is not None


def test_note_defaults_are_documentation_not_context(db, project, dana):
    """A note is reference-only until someone deliberately says otherwise.
    Defaulting to context would let a stray note move the estimate."""
    note = Note(project_id=project.id, scope="project", title="t", body="b",
                category="existing_condition", author_user_id=dana.id)
    db.add(note)
    db.flush()
    assert note.usage == "reference"
    assert note.status == "open"
    assert note.rfi_needed is False


def test_note_can_anchor_to_a_sheet_or_an_item(db, project, sheet, dana):
    note = Note(project_id=project.id, scope="sheet", scope_ref=sheet.id,
                title="t", body="b", category="existing_condition", author_user_id=dana.id)
    db.add(note)
    db.flush()
    assert note.scope_ref == sheet.id


def test_item_carries_the_engine_cluster_tag(db, project, sheet):
    """The merge key for an approval-preserving re-run. Counting is
    deterministic, so the same file yields the same tag on the same sheet
    -- without it there is nothing stable to match a re-run against."""
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle",
                name="20A duplex receptacle", system="Power", category="Devices",
                quantity=12, unit="ea", source_tag="R")
    db.add(item)
    db.flush()
    assert item.source_tag == "R"


def test_item_source_tag_defaults_empty(db, project, sheet):
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="panel",
                name="Panel", system="Power", category="Gear", quantity=1, unit="ea")
    db.add(item)
    db.flush()
    assert item.source_tag == ""
