from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from app.identity.models import Org
from app.takeoff import actions as actions_module
from app.takeoff.models import Action, Project, ReviewStatus


def test_commit_records_the_actor_and_a_label(db, dana, project, item):
    action = actions_module.commit(
        db, actor=dana, project_id=project.id, kind="approve", label="Approved 20A duplex receptacle",
        before={"status": "ready"}, after={"status": "approved"}, item_id=item.id,
    )
    db.flush()
    # Expire so the assertions below force a reload from the database --
    # expire_on_commit=False means the identity-mapped Python object would
    # otherwise satisfy these assertions even if JSONB persistence were
    # broken, since we'd just be comparing the dict to itself in memory.
    db.expire(action)

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


def test_the_database_refuses_to_truncate_actions(db, dana, project, item):
    actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    db.flush()

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("truncate actions"))


def test_the_guard_survives_session_replication_role_replica(db, dana, project, item):
    """ORIGIN triggers (the default) stop firing under
    session_replication_role = replica -- a mode a logical-replication
    apply worker or a bulk-load script can set. The guard was created
    ENABLE ALWAYS specifically so this doesn't open a bypass; prove it by
    setting replica mode ourselves and confirming the trigger still fires.

    SET LOCAL, not SET, so the setting is scoped to this transaction and
    is undone automatically when the fixture rolls back in teardown --
    it must not leak to whatever connection the pool hands the next test.
    """
    action = actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    db.flush()
    db.execute(text("set local session_replication_role = replica"))

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("update actions set label = 'rewritten' where id = :id"), {"id": action.id})


def test_deleting_a_project_with_actions_is_restricted_not_cascaded(db, dana, project, item):
    """actions.project_id must be ON DELETE RESTRICT, not CASCADE.

    Postgres implements FK cascade as a real DELETE issued through SPI,
    which would either be refused by the append-only trigger (making the
    project itself undeletable) or -- if it somehow bypassed the trigger
    -- erase the project's entire audit log in one statement. RESTRICT
    sidesteps the ambiguity entirely: the project delete is rejected by
    the foreign key before any action row is ever touched.
    """
    action = actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    db.flush()

    # A savepoint, not a plain rollback: the whole test session is one
    # open transaction with no intervening commit (per this suite's
    # convention), so a bare db.rollback() after the error would discard
    # the fixture data (project, item, dana) along with the failed
    # statement. begin_nested() scopes the rollback to just this attempt.
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(text("delete from projects where id = :id"), {"id": project.id})

    still_there = db.get(Action, action.id)
    assert still_there is not None


def test_before_and_after_round_trip_decimal_and_enum_through_jsonb(db, dana, project, item):
    """Item.quantity is Numeric -> Decimal in Python, and Item.status is a
    ReviewStatus enum member -- neither is JSON-serializable on its own.
    commit() must encode both automatically (Decimal -> str, enum ->
    .value) and the encoding must actually reach the database, not just
    survive in the in-memory object.
    """
    action = actions_module.commit(
        db, actor=dana, project_id=project.id, kind="approve", label="Approved",
        before={"status": ReviewStatus.READY, "quantity": Decimal("14.00")},
        after={"status": ReviewStatus.APPROVED, "quantity": Decimal("14.00")},
        item_id=item.id,
    )
    db.flush()
    db.expire(action)  # force the reload from the database, not the identity map

    assert action.before == {"status": "ready", "quantity": "14.00"}
    assert action.after == {"status": "approved", "quantity": "14.00"}

    assert actions_module.decode_snapshot_value(action.before["status"], ReviewStatus) is ReviewStatus.READY
    assert actions_module.decode_snapshot_value(action.before["quantity"], Decimal) == Decimal("14.00")


def test_seq_gives_a_total_order_within_the_same_transaction(db, dana, project, item):
    """created_at is the transaction timestamp -- identical for every row
    written in the same transaction, which the compound scale-confirmation
    flow does deliberately. seq must still separate them, since undo is
    LIFO and needs an unambiguous "most recent action."
    """
    first = actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="First",
                            before={}, after={}, item_id=item.id)
    second = actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="Second",
                            before={}, after={}, item_id=item.id)
    db.flush()

    assert first.created_at == second.created_at
    assert second.seq > first.seq


def test_only_one_action_can_undo_a_given_action(db, dana, project, item):
    original = actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    db.flush()

    actions_module.commit(db, actor=dana, project_id=project.id, kind="undo", label="Undo",
                            before={}, after={}, item_id=item.id, undoes_action_id=original.id)
    db.flush()

    actions_module.commit(db, actor=dana, project_id=project.id, kind="undo", label="Undo again",
                            before={}, after={}, item_id=item.id, undoes_action_id=original.id)
    with pytest.raises(IntegrityError):
        db.flush()


def test_commit_assigns_an_id_before_flush(db, dana, project, item):
    """id has a Python-side column default, which SQLAlchemy only
    evaluates at flush time -- so without an explicit assignment inside
    commit(), action.id would be None the moment commit() returns.
    Chaining undoes_action_id=prior.id before ever flushing (which a
    compound action legitimately needs to do) would silently write None
    into that nullable column.
    """
    original = actions_module.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    assert original.id is not None

    undo = actions_module.commit(db, actor=dana, project_id=project.id, kind="undo", label="Undo",
                            before={}, after={}, item_id=item.id, undoes_action_id=original.id)
    db.flush()

    assert undo.undoes_action_id == original.id


def test_commit_refuses_a_project_outside_the_actors_org(db, dana, item):
    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = Project(org_id=other_org.id, name="A different firm's project", revision_set_label="")
    db.add(other_project)
    db.flush()

    with pytest.raises(actions_module.CrossOrgActionError):
        actions_module.commit(
            db, actor=dana, project_id=other_project.id, kind="approve", label="Approved",
            before={}, after={}, item_id=item.id,
        )
