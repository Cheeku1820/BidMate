"""upsert_evidence_image is the one function both first-time ingest and a
reprocess re-run call to keep an item's evidence image in sync with what
the engine most recently produced for it."""
import uuid

from app.takeoff.evidence_images import upsert_evidence_image
from app.takeoff.models import Item, ItemEvidenceImage, ReviewStatus, Sheet


def _make_item(db, project):
    sheet = Sheet(id=uuid.uuid4(), project_id=project.id, number="E1.1", title="t",
                  discipline="Electrical", revision="", scale="", scale_options=[], plan="",
                  sort_order=0)
    db.add(sheet)
    db.flush()
    item = Item(id=uuid.uuid4(), project_id=project.id, sheet_id=sheet.id, symbol="receptacle",
                name="Receptacle", description="", system="Power", category="Devices",
                quantity=1, unit="ea", status=ReviewStatus.READY)
    db.add(item)
    db.flush()
    return item


def test_upsert_inserts_a_new_image(db, project):
    item = _make_item(db, project)
    upsert_evidence_image(db, item.id, b"first-png")
    db.commit()
    row = db.get(ItemEvidenceImage, item.id)
    assert row is not None and row.png == b"first-png"


def test_upsert_replaces_an_existing_image(db, project):
    item = _make_item(db, project)
    upsert_evidence_image(db, item.id, b"first-png")
    db.commit()
    upsert_evidence_image(db, item.id, b"second-png")
    db.commit()
    row = db.get(ItemEvidenceImage, item.id)
    assert row.png == b"second-png"


def test_upsert_clears_a_stale_image_when_png_is_none(db, project):
    """A re-run whose crop generation failed this time must not leave a
    previous run's image silently misrepresenting the current takeoff."""
    item = _make_item(db, project)
    upsert_evidence_image(db, item.id, b"first-png")
    db.commit()
    upsert_evidence_image(db, item.id, None)
    db.commit()
    assert db.get(ItemEvidenceImage, item.id) is None


def test_upsert_with_none_and_no_existing_row_is_a_no_op(db, project):
    item = _make_item(db, project)
    upsert_evidence_image(db, item.id, None)
    db.commit()
    assert db.get(ItemEvidenceImage, item.id) is None
