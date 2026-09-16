"""app/assistant/models.py's ConversationMessage -- one row per turn of a
project's thread. `role` uses the product's words (estimator / answer),
never user / assistant: a wire field is one copy change away from being
rendered (CLAUDE.md, no AI framing)."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.assistant.models import ROLES, ConversationMessage


def test_roles_are_product_words():
    assert ROLES == ("estimator", "answer")


def test_message_round_trips_with_its_screen(db, project, dana):
    m = ConversationMessage(project_id=project.id, role="estimator", text="What's blocking export?",
                            screen={"name": "export"}, created_by=dana.id)
    db.add(m)
    db.flush()
    loaded = db.get(ConversationMessage, m.id)
    assert loaded.role == "estimator"
    assert loaded.screen == {"name": "export"}
    assert loaded.created_at is not None


def test_answer_has_no_screen(db, project, dana):
    m = ConversationMessage(project_id=project.id, role="answer", text="Nothing is blocking.", created_by=dana.id)
    db.add(m)
    db.flush()
    assert db.get(ConversationMessage, m.id).screen is None


def test_role_outside_the_set_is_refused(db, project, dana):
    db.add(ConversationMessage(project_id=project.id, role="assistant", text="x", created_by=dana.id))
    with pytest.raises(IntegrityError):
        db.flush()
