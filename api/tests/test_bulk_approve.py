from datetime import datetime, timezone

from app.takeoff import bulk
from app.takeoff.models import Item, ReviewStatus


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
    from sqlalchemy import select
    from app.takeoff.models import Action

    actions = db.scalars(select(Action).where(Action.kind == "bulk_approve")).all()
    assert len(actions) == 1

    # The action carries enough per-item state to reverse the batch, not
    # merely a list of ids.
    before_items = result.action.before["items"]
    after_items = result.action.after["items"]
    assert set(before_items) == {str(a.id), str(b.id)}
    assert before_items[str(a.id)]["status"] == "ready"
    assert after_items[str(a.id)]["status"] == "approved"
    assert after_items[str(a.id)]["approved_by_user_id"] == str(dana.id)


def test_bulk_approval_ignores_items_from_another_project(db, dana, project, sheet, org):
    from app.takeoff.models import Project

    other = Project(org_id=org.id, name="Other project")
    db.add(other)
    db.flush()
    mine = _extra(db, project, sheet, ReviewStatus.READY)

    result = bulk.bulk_approve(db, dana, other.id, [mine.id])

    assert result.approved == []
    assert result.skipped[mine.id] == "not_in_project"
    assert result.action is None
    assert mine.status is ReviewStatus.READY


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

    assert result.approved == []
    assert result.action is None


def test_bulk_approval_with_empty_list_is_a_noop(db, dana, project):
    result = bulk.bulk_approve(db, dana, project.id, [])

    assert result.approved == []
    assert result.skipped == {}
    assert result.action is None
