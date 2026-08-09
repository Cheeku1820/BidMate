from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.errors import DomainError
from app.takeoff import actions
from app.takeoff.models import Item, ReviewStatus, Warning, WarningReason
from app.takeoff import review
from app.takeoff import snapshots


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


# --- I1: approve_item must recheck status under a lock, not a stale read ---


def test_approve_item_rechecks_status_under_a_row_lock_not_a_stale_read(db, dana, item):
    """Reviewer A (this session) loads the item while it is Ready to
    review. Reviewer B -- a separate connection and transaction --
    flips it to Missing information and commits. approve_item() must
    refuse based on the row's current state in the database, not
    whatever this session's Python object still says, or a concurrent
    reviewer's Missing information item could be waved through by a
    caller sitting on a stale read.

    db.commit() (rather than just flush) is required here, deliberately
    breaking from this suite's usual single-uncommitted-transaction
    pattern: a second, independent connection cannot see this session's
    fixtures at all until they are actually committed. The `db` fixture's
    teardown drops and recreates the whole schema regardless of commit
    state, so this is safe.
    """
    db.commit()

    other_engine = create_engine(settings.test_database_url)
    OtherSession = sessionmaker(bind=other_engine, expire_on_commit=False)
    other = OtherSession()
    try:
        other_item = other.get(Item, item.id)
        other_item.status = ReviewStatus.MISSING
        other.commit()
    finally:
        other.close()
        other_engine.dispose()

    # This session's own object still says Ready to review -- nothing in
    # this transaction has told it otherwise yet.
    assert item.status is ReviewStatus.READY

    with pytest.raises(DomainError) as caught:
        review.approve_item(db, dana, item)

    assert caught.value.code == "missing_information_blocks_approval"
    assert item.status is ReviewStatus.MISSING, "the row lock must refresh the stale in-memory read"


# --- I5: a rejected item cannot be approved as-is ---


def test_a_rejected_item_cannot_be_approved(db, dana, item):
    review.reject_item(db, dana, item)
    db.flush()

    with pytest.raises(DomainError) as caught:
        review.approve_item(db, dana, item)

    assert caught.value.code == "rejected_item_cannot_be_approved"
    assert item.status is ReviewStatus.READY, "the refusal must not touch review status either"


def test_unrejecting_then_approving_succeeds(db, dana, item):
    review.reject_item(db, dana, item)
    db.flush()
    review.unreject_item(db, dana, item)
    db.flush()

    review.approve_item(db, dana, item)

    assert item.status is ReviewStatus.APPROVED


# --- I2 / I3: delete_item snapshots warnings, and the snapshot decodes back ---


def test_deleting_an_item_snapshots_its_warnings_before_cascade_removes_them(db, dana, item):
    warning = Warning(
        item_id=item.id,
        reason=WarningReason.SCALE,
        title="Scale needs confirmation",
        found="E2.1 shows two scale labels.",
        why="Measured conduit lengths may be wrong.",
        fix="Select the scale that applies to this sheet.",
        where_="E2.1 title block",
    )
    db.add(warning)
    db.flush()
    warning_id = warning.id

    action = review.delete_item(db, dana, item)
    db.flush()
    db.expire(action)

    assert action.before["warnings"] == [{
        "id": str(warning_id),
        "item_id": str(item.id),
        "sheet_id": None,
        "reason": "scale",
        "title": "Scale needs confirmation",
        "found": "E2.1 shows two scale labels.",
        "why": "Measured conduit lengths may be wrong.",
        "fix": "Select the scale that applies to this sheet.",
        "where_": "E2.1 title block",
    }]


def test_decode_snapshot_reconstructs_a_deleted_items_typed_fields(db, dana, item):
    item_id = item.id
    action = review.delete_item(db, dana, item)
    db.flush()
    db.expire(action)

    restored = actions.decode_snapshot(action.before, snapshots.ITEM_SNAPSHOT_TYPES)

    assert restored["id"] == item_id
    assert restored["status"] is ReviewStatus.READY
    assert restored["quantity"] == Decimal("14.00")
    assert restored["warnings"] == []


def test_decode_snapshot_raises_for_a_field_with_no_type_given():
    with pytest.raises(KeyError):
        actions.decode_snapshot({"mystery_field": "x"}, {})


# --- I4: edit_item validates values, not just keys ---


def test_editing_category_to_a_blank_string_is_refused(db, dana, item):
    with pytest.raises(DomainError) as caught:
        review.edit_item(db, dana, item, {"category": "   "})

    assert caught.value.code == "field_cannot_be_empty"
    assert item.category == "Devices", "a refused edit must not have mutated the item"


def test_editing_quantity_to_a_non_numeric_value_is_a_domain_error_not_a_500(db, dana, item):
    with pytest.raises(DomainError) as caught:
        review.edit_item(db, dana, item, {"quantity": "fourteen"})

    assert caught.value.code == "invalid_quantity"


def test_editing_notes_to_null_is_refused(db, dana, item):
    with pytest.raises(DomainError) as caught:
        review.edit_item(db, dana, item, {"notes": None})

    assert caught.value.code == "field_cannot_be_empty"


# --- I6: quantity edits keep exact Decimal precision through the snapshot ---


def test_editing_quantity_to_a_fraction_round_trips_as_an_exact_decimal_string(db, dana, item):
    action = review.edit_item(db, dana, item, {"quantity": "12.55"})
    db.flush()
    db.expire(action)
    db.expire(item)

    assert item.quantity == Decimal("12.55")
    assert action.after["quantity"] == "12.55"
    assert isinstance(action.after["quantity"], str)


# --- Carry-forward fix: Decimal("NaN")/("Infinity") pass InvalidOperation
# but poison every SUM downstream, so the validator must reject them by
# name rather than relying on Decimal's parser alone. ---


@pytest.mark.parametrize("bad_value", ["NaN", "nan", "Infinity", "-Infinity", "inf"])
def test_editing_quantity_to_a_non_finite_value_is_refused(db, dana, item, bad_value):
    with pytest.raises(DomainError) as caught:
        review.edit_item(db, dana, item, {"quantity": bad_value})

    assert caught.value.code == "invalid_quantity"
    assert item.quantity == Decimal("14.00"), "a refused edit must not have mutated the item"


def test_editing_quantity_to_a_negative_value_is_refused(db, dana, item):
    """A takeoff quantity is a count or a measured length -- there is no
    such thing as -6 receptacles or -40 linear feet of conduit, so a
    negative value is not a valid edit rather than a value the estimator
    might legitimately want."""
    with pytest.raises(DomainError) as caught:
        review.edit_item(db, dana, item, {"quantity": "-1"})

    assert caught.value.code == "invalid_quantity"
    assert item.quantity == Decimal("14.00")


def test_editing_quantity_to_zero_is_accepted(db, dana, item):
    """Zero is not negative -- an item counted at zero is a legitimate
    intermediate state (a run still being traced, say), distinct from a
    value nobody would legitimately enter."""
    action = review.edit_item(db, dana, item, {"quantity": "0"})
    db.flush()

    assert item.quantity == Decimal("0")
    assert action.after["quantity"] == "0"


# --- Review finding F: a quantity within Decimal's finite range can still
# overflow Item.quantity (Numeric(12, 2)) at flush, as a bare psycopg
# error with no recovery copy, unless the validator bounds it itself. ---


def test_editing_quantity_beyond_the_column_bound_is_refused(db, dana, item):
    with pytest.raises(DomainError) as caught:
        review.edit_item(db, dana, item, {"quantity": "1E+15"})

    assert caught.value.code == "invalid_quantity"
    assert item.quantity == Decimal("14.00"), "a refused edit must not have mutated the item"


def test_editing_quantity_at_the_column_bound_is_accepted(db, dana, item):
    action = review.edit_item(db, dana, item, {"quantity": "9999999999.99"})
    db.flush()

    assert item.quantity == Decimal("9999999999.99")
    assert action.after["quantity"] == "9999999999.99"


# --- Carry-forward fix: approve_item's locked re-read must not surface a
# concurrent delete as an unhandled 500 ---


def test_approving_an_item_deleted_by_a_concurrent_reviewer_is_a_domain_error(db, dana, item):
    """Reviewer A (this session) holds a reference to `item`. Reviewer B
    -- a separate connection and transaction -- deletes the row and
    commits. approve_item()'s locked re-read (`.with_for_update()`) must
    not raise NoResultFound as a bare 500 with no recovery copy; it
    should refuse with a DomainError naming what happened.
    """
    db.commit()

    other_engine = create_engine(settings.test_database_url)
    OtherSession = sessionmaker(bind=other_engine, expire_on_commit=False)
    other = OtherSession()
    try:
        other_item = other.get(Item, item.id)
        other.delete(other_item)
        other.commit()
    finally:
        other.close()
        other_engine.dispose()

    with pytest.raises(DomainError) as caught:
        review.approve_item(db, dana, item)

    assert caught.value.code == "item_no_longer_exists"
