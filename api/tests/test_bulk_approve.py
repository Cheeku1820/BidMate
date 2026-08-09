import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.identity.models import Org
from app.takeoff import bulk
from app.takeoff.actions import CrossOrgActionError
from app.takeoff.models import Action, Item, Project, ReviewStatus


def _extra(db, project, sheet, status):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="switch", name=f"item {status.value}",
              system="Lighting", category="Devices", quantity=1, unit="EA", status=status)
    db.add(i)
    db.flush()
    return i


def test_only_ready_items_are_approved(db, dana, project, sheet):
    ready = _extra(db, project, sheet, ReviewStatus.READY)
    attention = _extra(db, project, sheet, ReviewStatus.ATTENTION)
    missing = _extra(db, project, sheet, ReviewStatus.MISSING)

    result = bulk.bulk_approve(db, dana, project.id, [ready.id, attention.id, missing.id])
    db.flush()

    assert result.approved == [ready.id]
    assert result.skipped[attention.id] == "not_ready_to_review"
    assert result.skipped[missing.id] == "not_ready_to_review"
    assert attention.status is ReviewStatus.ATTENTION
    assert missing.status is ReviewStatus.MISSING

    # Not just the in-session objects -- re-read from the database to be
    # sure the skip was real and not merely an unflushed in-memory value.
    db.expire_all()
    fresh_attention = db.get(Item, attention.id)
    fresh_missing = db.get(Item, missing.id)
    assert fresh_attention.status is ReviewStatus.ATTENTION
    assert fresh_attention.approved_at is None
    assert fresh_attention.approved_by_user_id is None
    assert fresh_missing.status is ReviewStatus.MISSING
    assert fresh_missing.approved_at is None
    assert fresh_missing.approved_by_user_id is None

    fresh_ready = db.get(Item, ready.id)
    assert fresh_ready.status is ReviewStatus.APPROVED
    assert fresh_ready.approved_by_user_id == dana.id
    assert fresh_ready.approved_at is not None


def test_bulk_approval_writes_one_action_not_one_per_item(db, dana, project, sheet):
    a = _extra(db, project, sheet, ReviewStatus.READY)
    b = _extra(db, project, sheet, ReviewStatus.READY)

    result = bulk.bulk_approve(db, dana, project.id, [a.id, b.id])
    db.flush()

    assert result.action is not None
    assert result.action.kind == "bulk_approve"
    assert result.action.label == "Approved 2 items"

    # Exactly one row landed in the append-only log for this batch.
    actions = db.scalars(select(Action).where(Action.kind == "bulk_approve")).all()
    assert len(actions) == 1

    # The action carries enough per-item state to reverse the batch, not
    # merely a list of ids. Re-read the row from the database -- rather
    # than trusting the in-memory `Action` object -- so the assertion
    # covers the actual JSONB shape Task 10's undo will read back.
    db.expire_all()
    stored = db.get(Action, result.action.id)
    before_items = stored.before[bulk.ITEMS_SNAPSHOT_KEY]
    after_items = stored.after[bulk.ITEMS_SNAPSHOT_KEY]
    assert set(before_items) == {str(a.id), str(b.id)}
    assert before_items[str(a.id)]["status"] == "ready"
    assert before_items[str(a.id)]["approved_by_user_id"] is None
    assert after_items[str(a.id)]["status"] == "approved"
    assert after_items[str(a.id)]["approved_by_user_id"] == str(dana.id)
    assert after_items[str(a.id)]["approved_at"] is not None


def test_bulk_approval_ignores_items_from_another_project(db, dana, project, sheet, org):
    other = Project(org_id=org.id, name="Other project")
    db.add(other)
    db.flush()
    mine = _extra(db, project, sheet, ReviewStatus.READY)

    result = bulk.bulk_approve(db, dana, other.id, [mine.id])
    db.flush()

    assert result.approved == []
    assert result.skipped[mine.id] == "not_in_project"
    assert result.action is None

    db.expire_all()
    fresh = db.get(Item, mine.id)
    assert fresh.status is ReviewStatus.READY
    assert fresh.approved_by_user_id is None
    assert fresh.approved_at is None


def test_bulk_approval_skips_rejected_item_even_when_status_is_ready(db, dana, project, sheet):
    rejected = _extra(db, project, sheet, ReviewStatus.READY)
    rejected.rejected_at = datetime.now(timezone.utc)
    rejected.rejected_by_user_id = dana.id
    db.flush()

    result = bulk.bulk_approve(db, dana, project.id, [rejected.id])
    db.flush()

    assert result.approved == []
    assert result.skipped[rejected.id] == "rejected"
    assert result.action is None

    db.expire_all()
    fresh = db.get(Item, rejected.id)
    assert fresh.status is ReviewStatus.READY
    assert fresh.approved_at is None


def test_bulk_approval_reports_no_action_when_nothing_is_approved(db, dana, project, sheet):
    attention = _extra(db, project, sheet, ReviewStatus.ATTENTION)

    result = bulk.bulk_approve(db, dana, project.id, [attention.id])
    db.flush()

    assert result.approved == []
    assert result.action is None

    db.expire_all()
    fresh = db.get(Item, attention.id)
    assert fresh.status is ReviewStatus.ATTENTION
    assert fresh.approved_at is None
    assert fresh.approved_by_user_id is None


def test_bulk_approval_with_empty_list_is_a_noop(db, dana, project):
    result = bulk.bulk_approve(db, dana, project.id, [])

    assert result.approved == []
    assert result.skipped == {}
    assert result.action is None


def test_bulk_approval_skips_an_already_approved_item_with_its_own_reason(db, dana, project, sheet):
    """Distinct from `not_ready_to_review`: nothing is wrong with an
    already-approved item, so it must not be reported the same way as a
    Needs attention or Missing information item, which is work the
    estimator has to go do.
    """
    approved = _extra(db, project, sheet, ReviewStatus.READY)
    first = bulk.bulk_approve(db, dana, project.id, [approved.id])
    db.flush()
    assert first.approved == [approved.id]

    second = bulk.bulk_approve(db, dana, project.id, [approved.id])
    db.flush()

    assert second.approved == []
    assert second.skipped[approved.id] == "already_approved"
    assert second.skipped[approved.id] != "not_ready_to_review"
    assert second.action is None


def test_bulk_approval_deduplicates_repeated_ids(db, dana, project, sheet):
    """A repeated id in the request must be approved once, not counted
    twice and not left in both `approved` and `skipped`.
    """
    ready = _extra(db, project, sheet, ReviewStatus.READY)

    result = bulk.bulk_approve(db, dana, project.id, [ready.id, ready.id, ready.id])
    db.flush()

    assert result.approved == [ready.id]
    assert ready.id not in result.skipped
    assert result.action.label == "Approved 1 item"

    db.expire_all()
    fresh = db.get(Item, ready.id)
    assert fresh.status is ReviewStatus.APPROVED


def test_bulk_approval_refuses_a_project_outside_the_actors_org(db, dana, project, sheet, org):
    """Authorization has to run before anything is read or locked --
    otherwise an actor from another org could pass any project id and
    learn per-item review state (exists / rejected / already approved /
    needs attention) for a firm's project they have no right to see.
    """
    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = Project(org_id=other_org.id, name="A different firm's project")
    db.add(other_project)
    db.flush()
    ready = _extra(db, project, sheet, ReviewStatus.READY)

    with pytest.raises(CrossOrgActionError):
        bulk.bulk_approve(db, dana, other_project.id, [ready.id])

    # Nothing moved -- not the item, and no action was written.
    db.expire_all()
    fresh = db.get(Item, ready.id)
    assert fresh.status is ReviewStatus.READY
    actions = db.scalars(select(Action).where(Action.kind == "bulk_approve")).all()
    assert actions == []


def test_bulk_approval_refuses_cross_org_even_with_no_qualifying_items(db, dana, org):
    """The vulnerable path: previously, when nothing in the batch
    qualified for approval, `commit()` (the only place the org check
    ran) was never called, so no authorization check ran at all -- an
    actor could probe an arbitrary project id with arbitrary item ids
    and read back skip reasons for items that were never theirs to see.
    """
    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = Project(org_id=other_org.id, name="A different firm's project")
    db.add(other_project)
    db.flush()

    with pytest.raises(CrossOrgActionError):
        bulk.bulk_approve(db, dana, other_project.id, [uuid.uuid4()])
