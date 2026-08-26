from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.identity.models import Org
from app.takeoff import scale as scale_module
from app.takeoff.actions import CrossOrgActionError
from app.takeoff.models import Action, Item, Project, ReviewStatus, Sheet, Warning, WarningReason


def _blocked(db, project, sheet):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="run", name='2" EMT conduit run',
             system="Power", category="Conduit and wire", quantity=184, unit="LF",
             status=ReviewStatus.MISSING, path=[[186, 226], [186, 430]])
    db.add(i)
    db.flush()
    db.add(Warning(item_id=i.id, reason=WarningReason.SCALE, title="Missing scale reference",
                   found="No scale label was found.", why="This run could not be measured.",
                   fix="Set the drawing scale.", where_="E1.1 title block"))
    db.flush()
    return i


def _legend_blocked(db, project, sheet):
    """An item Missing information for a reason set_scale() has no
    business resolving -- its symbol isn't in the legend, not its
    sheet's scale.
    """
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="unknown", name="Unclassified symbol",
             system="Power", category="Unclassified", quantity=1, unit="EA",
             status=ReviewStatus.MISSING, x=400, y=300)
    db.add(i)
    db.flush()
    db.add(Warning(item_id=i.id, reason=WarningReason.LEGEND, title="Symbol not in legend",
                   found="This symbol does not appear in the E0.1 legend.",
                   why="It cannot be counted without knowing what it is.",
                   fix="Classify the symbol or confirm it against the legend.", where_="E0.1 legend"))
    db.flush()
    return i


def test_setting_the_scale_releases_every_blocked_item_on_that_sheet(db, dana, project, sheet):
    one, two = _blocked(db, project, sheet), _blocked(db, project, sheet)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert sheet.scale == '1/8" = 1\'-0"'
    assert one.status is ReviewStatus.READY
    assert two.status is ReviewStatus.READY


def test_the_warnings_on_released_items_are_cleared(db, dana, project, sheet):
    item = _blocked(db, project, sheet)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert db.query(Warning).filter(Warning.item_id == item.id).count() == 0


def test_it_is_one_action_naming_how_many_items_moved(db, dana, project, sheet):
    _blocked(db, project, sheet)
    _blocked(db, project, sheet)

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.kind == "scale"
    assert "2 measured items" in action.label
    assert len(action.before["items"]) == 2


def test_items_on_another_sheet_are_untouched(db, dana, project, sheet):
    other = Sheet(project_id=project.id, number="E1.1", title="Lighting plan", discipline="Electrical",
                  revision="Rev 3", scale="none", scale_options=[], plan="office")
    db.add(other)
    db.flush()
    elsewhere = _blocked(db, project, other)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert elsewhere.status is ReviewStatus.MISSING


def test_the_recorded_action_carries_enough_to_reverse_both_halves(db, dana, project, sheet):
    """Task 10 has to restore the sheet's previous scale AND every
    released item's previous status AND the warning that explained it --
    so the compound action's `before` must carry the sheet's old scale,
    each item's id and prior status, and each item's warning fields, not
    just item ids and statuses.
    """
    item = _blocked(db, project, sheet)

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.before["scale"] == "mixed"
    assert action.after["scale"] == '1/8" = 1\'-0"'

    before_item = action.before["items"][0]
    assert before_item["id"] == str(item.id)
    assert before_item["status"] == "missing"
    assert len(before_item["warnings"]) == 1
    assert before_item["warnings"][0]["reason"] == "scale"
    assert before_item["warnings"][0]["title"] == "Missing scale reference"
    assert before_item["warnings"][0]["found"] == "No scale label was found."
    assert before_item["warnings"][0]["why"] == "This run could not be measured."
    assert before_item["warnings"][0]["fix"] == "Set the drawing scale."
    assert before_item["warnings"][0]["where_"] == "E1.1 title block"


def test_a_missing_item_with_no_warning_at_all_is_left_untouched(db, dana, project, sheet):
    """There is no basis to call this item scale-blocked -- it carries no
    warning of any reason -- so set_scale() must not sweep it up just
    because its status happens to read Missing information.
    """
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="run", name='2" EMT conduit run',
                system="Power", category="Conduit and wire", quantity=184, unit="LF",
                status=ReviewStatus.MISSING, path=[[186, 226], [186, 430]])
    db.add(item)
    db.flush()

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert item.status is ReviewStatus.MISSING
    assert action.before["items"] == []


def test_setting_the_scale_on_a_sheet_with_no_blocked_items_still_records_one_action(db, dana, project, sheet):
    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.kind == "scale"
    assert sheet.scale == '1/8" = 1\'-0"'
    assert action.before["items"] == []
    assert "0 measured items" in action.label


# --- Product decision: Missing information covers more than a missing
# scale (a legend gap, for one). set_scale() must release only items
# whose blocking warning actually carries the scale reason. ---


def test_an_item_blocked_only_by_a_legend_warning_is_left_untouched(db, dana, project, sheet):
    """The failure this decision exists to prevent: previously,
    confirming a scale released every Missing information item on the
    sheet, including one whose symbol simply isn't in the legend --
    deleting the warning that explained why it was never countable and
    leaving it eligible for bulk approval with a guessed quantity.
    """
    item = _legend_blocked(db, project, sheet)

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert item.status is ReviewStatus.MISSING
    remaining = db.scalars(select(Warning).where(Warning.item_id == item.id)).all()
    assert len(remaining) == 1
    assert remaining[0].reason is WarningReason.LEGEND
    assert all(entry["id"] != str(item.id) for entry in action.before["items"])


def test_an_item_blocked_on_both_scale_and_legend_stays_missing_with_its_legend_warning_intact(
    db, dana, project, sheet
):
    """The whole point of the reason field: an item can be Missing
    information for two independent reasons at once. Confirming the
    scale resolves its scale half -- that warning is deleted -- but must
    never release the item outright or touch the legend warning that
    still, correctly, blocks it.
    """
    item = _blocked(db, project, sheet)
    db.add(Warning(item_id=item.id, reason=WarningReason.LEGEND, title="Symbol not in legend",
                   found="This symbol does not appear in the E0.1 legend.",
                   why="It cannot be counted without knowing what it is.",
                   fix="Classify the symbol or confirm it against the legend.", where_="E0.1 legend"))
    db.flush()

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert item.status is ReviewStatus.MISSING
    remaining = db.scalars(select(Warning).where(Warning.item_id == item.id)).all()
    assert len(remaining) == 1
    assert remaining[0].reason is WarningReason.LEGEND
    assert remaining[0].title == "Symbol not in legend"


# --- Finding B: authorization must run before any row is locked ---


def test_set_scale_refuses_a_sheet_outside_the_actors_org(db, dana):
    """Locking rows is itself an effect a caller outside the sheet's org
    must never be able to trigger -- the same reasoning `bulk.py`'s
    authorization-first fix applies. Resolving the project and comparing
    org has to happen before either locking select runs.
    """
    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = Project(org_id=other_org.id, name="A different firm's project")
    db.add(other_project)
    db.flush()
    other_sheet = Sheet(project_id=other_project.id, number="E2.1", title="Power plan — warehouse",
                        discipline="Electrical", revision="Rev 2", scale="mixed", scale_options=[],
                        plan="warehouse")
    db.add(other_sheet)
    db.flush()
    item = _blocked(db, other_project, other_sheet)

    with pytest.raises(CrossOrgActionError):
        scale_module.set_scale(db, dana, other_sheet, '1/8" = 1\'-0"')

    db.expire_all()
    fresh_sheet = db.get(Sheet, other_sheet.id)
    fresh_item = db.get(Item, item.id)
    assert fresh_sheet.scale == "mixed"
    assert fresh_item.status is ReviewStatus.MISSING
    assert db.scalars(select(Action).where(Action.kind == "scale")).all() == []


# --- Finding D / E: the sheet row (and every candidate item) must be
# locked and re-read under FOR UPDATE with populate_existing=True, not
# read from whatever this session happened to load earlier ---


def test_set_scale_rereads_the_sheets_prior_scale_under_a_row_lock_not_a_stale_read(db, dana, project, sheet):
    """Reviewer A (this session) loads the sheet while its scale reads
    "mixed". Reviewer B -- a separate connection and transaction --
    changes it and commits. set_scale() must record the row's actual
    value at lock time as `before["scale"]`, not whatever this session's
    Python object still says -- otherwise the compound action claims a
    predecessor scale that was never actually the sheet's, and Task 10's
    undo would restore a value that was never true.

    db.commit() (rather than just flush) is required here, the same
    deliberate break from this suite's usual pattern used in
    test_review_state_machine.py's equivalent for approve_item: a second,
    independent connection cannot see this session's fixtures at all
    until they are actually committed.
    """
    db.commit()

    other_engine = create_engine(settings.test_database_url)
    OtherSession = sessionmaker(bind=other_engine, expire_on_commit=False)
    other = OtherSession()
    try:
        other_sheet = other.get(Sheet, sheet.id)
        other_sheet.scale = "1/4\" = 1'-0\""
        other.commit()
    finally:
        other.close()
        other_engine.dispose()

    # This session's own object still says the old value -- nothing in
    # this transaction has told it otherwise yet.
    assert sheet.scale == "mixed"

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.before["scale"] == "1/4\" = 1'-0\"", "must record the row's real prior value, not a stale read"
    assert sheet.scale == '1/8" = 1\'-0"', "the row lock must refresh the stale in-memory read"


def test_set_scale_rereads_an_items_status_under_a_row_lock_not_a_stale_read(db, dana, project, sheet):
    """This session loads the item while its status still reads Ready to
    review. Reviewer B -- a separate connection and transaction -- flips
    it to Missing information (adding a scale warning, so it becomes a
    genuine candidate, and a legend warning, so it is expected to stay
    Missing information even once released from the scale problem) and
    commits.

    The candidate query matches the row's real, current status -- that
    part happens at the database, so it can't go stale -- but the Python
    object it returns must also be refreshed by the lock. Without that,
    the code's `if not other_warnings` check would still see this
    session's stale "ready" read reflected nowhere useful (the object
    already claims a status not worth changing), silently skip flipping
    it, and leave the actual database row exactly as reviewer B left it
    -- Missing information -- while a stale in-memory "ready" masks
    that from any caller checking `item.status`. A correct re-read shows
    "missing" here, distinguishably, because a legend warning survives.
    """
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="run", name='2" EMT conduit run',
                system="Power", category="Conduit and wire", quantity=184, unit="LF",
                status=ReviewStatus.READY, path=[[186, 226], [186, 430]])
    db.add(item)
    db.commit()

    other_engine = create_engine(settings.test_database_url)
    OtherSession = sessionmaker(bind=other_engine, expire_on_commit=False)
    other = OtherSession()
    try:
        other_item = other.get(Item, item.id)
        other_item.status = ReviewStatus.MISSING
        other.add(Warning(item_id=item.id, reason=WarningReason.SCALE, title="Missing scale reference",
                          found="No scale label was found.", why="This run could not be measured.",
                          fix="Set the drawing scale.", where_="E1.1 title block"))
        other.add(Warning(item_id=item.id, reason=WarningReason.LEGEND, title="Symbol not in legend",
                          found="This symbol does not appear in the E0.1 legend.",
                          why="It cannot be counted without knowing what it is.",
                          fix="Classify the symbol or confirm it against the legend.", where_="E0.1 legend"))
        other.commit()
    finally:
        other.close()
        other_engine.dispose()

    assert item.status is ReviewStatus.READY, "this session's own object still says the old value"

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert len(action.before["items"]) == 1
    assert action.before["items"][0]["status"] == "missing", \
        "must record the row's real prior status, not a stale read"
    assert item.status is ReviewStatus.MISSING, "the row lock must refresh the stale in-memory read"
    remaining = db.scalars(select(Warning).where(Warning.item_id == item.id)).all()
    assert len(remaining) == 1 and remaining[0].reason is WarningReason.LEGEND


# --- Smaller items from the review ---


def test_setting_the_scale_writes_exactly_one_action_row(db, dana, project, sheet):
    """"One undo, not fourteen" is this task's headline requirement --
    verified here directly against the append-only log, not just
    structurally through the returned Action.
    """
    _blocked(db, project, sheet)
    _blocked(db, project, sheet)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    written = db.scalars(select(Action).where(Action.kind == "scale")).all()
    assert len(written) == 1


def test_a_rejected_item_is_excluded_from_release(db, dana, project, sheet):
    """An estimator who already rejected an item must not see it flipped
    back to Ready to review out from under them just because a scale was
    confirmed -- rejection is tracked independently of status, matching
    `bulk.bulk_approve()`'s treatment of a rejected item.
    """
    item = _blocked(db, project, sheet)
    item.rejected_at = datetime.now(timezone.utc)
    item.rejected_by_user_id = dana.id
    db.flush()

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert item.status is ReviewStatus.MISSING
    assert db.query(Warning).filter(Warning.item_id == item.id).count() == 1
    assert all(entry["id"] != str(item.id) for entry in action.before["items"])
