import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError, ProgrammingError

from app.takeoff import actions as actions_module
from app.takeoff.models import Action


def test_commit_records_the_actor_and_a_label(db, dana, project, item):
    action = actions_module.commit(
        db, actor=dana, project_id=project.id, kind="approve", label="Approved 20A duplex receptacle",
        before={"status": "ready"}, after={"status": "approved"}, item_id=item.id,
    )
    db.flush()

    assert action.actor_user_id == dana.id
    assert action.label == "Approved 20A duplex receptacle"
    assert action.before == {"status": "ready"}


def test_the_database_refuses_to_update_an_action(db, dana, project, item):
    action = actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    db.flush()

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("update actions set label = 'rewritten' where id = :id"), {"id": action.id})


def test_the_database_refuses_to_delete_an_action(db, dana, project, item):
    action = actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    db.flush()

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("delete from actions where id = :id"), {"id": action.id})
