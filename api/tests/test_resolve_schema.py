"""The columns and table behind the decision area (say-what-it-is spec)."""
import uuid

from sqlalchemy import select

from app.takeoff.models import Item, SymbolResolution


def test_items_carry_reject_reason_and_resolve_note(db, item):
    item.reject_reason = "not a device"
    item.resolve_note = "type F per E-501"
    db.flush()
    db.expire_all()
    fresh = db.get(Item, item.id)
    assert fresh.reject_reason == "not a device" and fresh.resolve_note == "type F per E-501"


def test_symbol_resolution_is_unique_per_project_and_tag(db, org, project, dana):
    from sqlalchemy.exc import IntegrityError

    db.add(SymbolResolution(org_id=org.id, project_id=project.id, tag="F", name="2x4 LED troffer",
                            system="Lighting", category="Fixtures", catalog_id=None, resolved_by_user_id=dana.id))
    db.flush()
    db.add(SymbolResolution(org_id=org.id, project_id=project.id, tag="F", name="something else",
                            system="Lighting", category="Fixtures", catalog_id=None, resolved_by_user_id=dana.id))
    try:
        db.flush()
        assert False, "second row for the same (project, tag) should be refused"
    except IntegrityError:
        db.rollback()


def test_commit_stores_a_note(db, item, dana):
    from app.takeoff.actions import commit

    action = commit(db, actor=dana, project_id=item.project_id, kind="edit", label="x", before={}, after={}, item_id=item.id, note="type F per E-501")
    db.flush()
    assert action.note == "type F per E-501"


def test_item_out_carries_the_two_fields(client, db, item, signed_in_user):
    item.resolve_note = "type F per E-501"
    db.commit()
    body = client.get(f"/api/projects/{item.project_id}/snapshot").json()
    row = next(i for i in body["items"] if i["id"] == str(item.id))
    assert row["resolve_note"] == "type F per E-501"
    assert row["reject_reason"] is None
