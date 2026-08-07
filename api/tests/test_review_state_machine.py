import pytest

from app.errors import DomainError
from app.takeoff import review
from app.takeoff.models import ReviewStatus


def test_approving_records_who_approved_it(db, dana, item):
    review.approve_item(db, dana, item)
    db.flush()

    assert item.status is ReviewStatus.APPROVED
    assert item.approved_by_user_id == dana.id
    assert item.approved_at is not None


def test_a_missing_information_item_cannot_be_approved(db, dana, item):
    item.status = ReviewStatus.MISSING
    db.flush()

    with pytest.raises(DomainError) as caught:
        review.approve_item(db, dana, item)

    assert caught.value.code == "missing_information_blocks_approval"
    assert item.status is ReviewStatus.MISSING


def test_a_needs_attention_item_can_be_approved(db, dana, item):
    item.status = ReviewStatus.ATTENTION
    db.flush()

    review.approve_item(db, dana, item)

    assert item.status is ReviewStatus.APPROVED


def test_rejecting_leaves_the_review_status_intact(db, dana, item):
    item.status = ReviewStatus.ATTENTION
    db.flush()

    review.reject_item(db, dana, item)
    db.flush()

    assert item.rejected_at is not None
    assert item.status is ReviewStatus.ATTENTION, "rejection must not destroy the review state"


def test_unrejecting_restores_the_item_without_guessing_a_status(db, dana, item):
    item.status = ReviewStatus.ATTENTION
    review.reject_item(db, dana, item)
    db.flush()

    review.unreject_item(db, dana, item)
    db.flush()

    assert item.rejected_at is None
    assert item.status is ReviewStatus.ATTENTION


def test_editing_an_unclassified_item_moves_it_to_ready(db, dana, item):
    item.status = ReviewStatus.ATTENTION
    item.category = "Unclassified"
    db.flush()

    review.edit_item(db, dana, item, {"category": "Devices"})
    db.flush()

    assert item.status is ReviewStatus.READY


def test_editing_rejects_a_field_that_is_not_editable(db, dana, item):
    with pytest.raises(DomainError) as caught:
        review.edit_item(db, dana, item, {"status": "approved"})

    assert caught.value.code == "field_not_editable"
