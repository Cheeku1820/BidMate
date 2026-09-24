"""The proposal a panel answer offered, recorded on its own message row.
The authoritative change lives in items, notes, scope and plan
decisions; this column only says what was offered and what became of
it, so a reloaded thread can render the card it already showed."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.assistant.models import ConversationMessage


def _answer(db, project, dana, **over):
    fields = dict(project_id=project.id, role="answer", text="Six items on E2.1 read as type F.",
                  created_by=dana.id)
    fields.update(over)
    row = ConversationMessage(**fields)
    db.add(row)
    return row


def test_an_answer_can_carry_a_proposal_and_its_status(db, project, dana):
    row = _answer(db, project, dana, proposal={"kind": "note", "summary": "Record a note"}, proposal_status="offered")
    db.flush()
    db.expire(row)
    assert row.proposal["kind"] == "note" and row.proposal_status == "offered"


def test_an_answer_without_a_proposal_has_neither(db, project, dana):
    row = _answer(db, project, dana)
    db.flush()
    assert row.proposal is None and row.proposal_status is None


def test_a_status_without_a_proposal_is_refused(db, project, dana):
    _answer(db, project, dana, proposal_status="applied")
    with pytest.raises(IntegrityError):
        db.flush()


def test_the_status_set_is_closed(db, project, dana):
    _answer(db, project, dana, proposal={"kind": "note"}, proposal_status="approved")
    with pytest.raises(IntegrityError):
        db.flush()
