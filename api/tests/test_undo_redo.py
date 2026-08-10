from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.errors import DomainError
from app.identity.models import Org, User
from app.takeoff import bulk, review, scale as scale_module, undo, undo_apply
from app.takeoff.actions import CrossOrgActionError
from app.takeoff.models import Action, Item, Project, ReviewStatus, Warning, WarningReason


def _blocked(db, project, sheet):
    """An item Missing information because its sheet has no confirmed
    scale -- matches test_scale.py's fixture so undo's warning-restore
    path is exercised against the same shape scale.py actually writes.
    """
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


def _foreign_project(db):
    """A project belonging to an org `dana` has no membership in, for
    the cross-org authorization tests."""
    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = Project(org_id=other_org.id, name="A different firm's project")
    db.add(other_project)
    db.flush()
    return other_project


# --- Brief's six, adjusted for the corrected snapshot shapes ---


def test_undo_restores_the_previous_status(db, dana, project, item):
    review.approve_item(db, dana, item)
    db.flush()

    undo.undo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.READY


def test_undo_appends_rather_than_deleting_history(db, dana, project, item):
    review.approve_item(db, dana, item)
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()

    assert db.query(Action).count() == 2


def test_redo_reapplies_the_action(db, dana, project, item):
    review.approve_item(db, dana, item)
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()

    undo.redo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.APPROVED


def test_undo_merges_only_the_fields_the_action_touched(db, dana, project, item):
    """B undoing A's approval must not clobber an unrelated quantity edit,
    and undoing the edit first must not resurrect the approval."""
    review.approve_item(db, dana, item)
    db.flush()
    review.edit_item(db, dana, item, {"quantity": 99})
    db.flush()

    # undo the edit, then the approval
    undo.undo(db, dana, project.id)
    db.flush()
    assert item.quantity == Decimal("14.00"), "undoing the edit should restore the prior quantity"
    assert item.status is ReviewStatus.APPROVED, "undoing the edit must not touch the approval"

    undo.undo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.READY
    assert item.quantity == Decimal("14.00"), "undoing the approval must not touch the quantity edit's result"


def test_undoing_a_scale_reverses_both_halves_together(db, dana, project, sheet):
    blocked = _blocked(db, project, sheet)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()
    assert blocked.status is ReviewStatus.READY
    assert db.query(Warning).filter(Warning.item_id == blocked.id).count() == 0

    undo.undo(db, dana, project.id)
    db.flush()

    assert sheet.scale == "mixed"
    assert blocked.status is ReviewStatus.MISSING

    # The part that separates a working undo from one that silently
    # destroys evidence: the scale warning set_scale() deleted must come
    # back, not just the item's status flag.
    restored = db.query(Warning).filter(Warning.item_id == blocked.id).all()
    assert len(restored) == 1
    assert restored[0].reason is WarningReason.SCALE
    assert restored[0].title == "Missing scale reference"
    assert restored[0].found == "No scale label was found."
    assert restored[0].why == "This run could not be measured."
    assert restored[0].fix == "Set the drawing scale."
    assert restored[0].where_ == "E1.1 title block"


def test_undo_head_is_none_on_a_project_with_no_actions(db, dana, project):
    assert undo.undo_head(db, dana, project.id) is None


# --- Beyond the brief: bulk_approve, delete, seq-ordering, and the
# scale/redo warning-deletion edge case ---


def test_undoing_a_bulk_approve_reverses_the_whole_batch(db, dana, project, sheet):
    one = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="Receptacle A",
               system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY)
    two = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="Receptacle B",
               system="Power", category="Devices", quantity=2, unit="EA", status=ReviewStatus.READY)
    db.add_all([one, two])
    db.flush()

    result = bulk.bulk_approve(db, dana, project.id, [one.id, two.id])
    db.flush()
    assert set(result.approved) == {one.id, two.id}
    assert one.status is ReviewStatus.APPROVED
    assert two.status is ReviewStatus.APPROVED

    undo.undo(db, dana, project.id)
    db.flush()

    assert one.status is ReviewStatus.READY
    assert one.approved_by_user_id is None
    assert one.approved_at is None
    assert two.status is ReviewStatus.READY
    assert two.approved_by_user_id is None
    assert two.approved_at is None


def test_redoing_a_bulk_approve_reapproves_the_whole_batch(db, dana, project, sheet):
    one = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="Receptacle A",
               system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY)
    two = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="Receptacle B",
               system="Power", category="Devices", quantity=2, unit="EA", status=ReviewStatus.READY)
    db.add_all([one, two])
    db.flush()

    bulk.bulk_approve(db, dana, project.id, [one.id, two.id])
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()

    undo.redo(db, dana, project.id)
    db.flush()

    assert one.status is ReviewStatus.APPROVED
    assert two.status is ReviewStatus.APPROVED


def test_undoing_a_delete_restores_the_item_with_its_warnings(db, dana, project, item):
    warning = Warning(item_id=item.id, reason=WarningReason.SCALE, title="Scale needs confirmation",
                       found="E2.1 shows two scale labels.", why="Measured conduit lengths may be wrong.",
                       fix="Select the scale that applies to this sheet.", where_="E2.1 title block")
    db.add(warning)
    db.flush()
    item_id = item.id
    original_quantity = item.quantity
    original_name = item.name

    review.delete_item(db, dana, item)
    db.flush()
    assert db.get(Item, item_id) is None

    undo.undo(db, dana, project.id)
    db.flush()

    restored = db.get(Item, item_id)
    assert restored is not None
    assert restored.name == original_name
    assert restored.quantity == original_quantity
    assert restored.status is ReviewStatus.READY

    restored_warnings = db.query(Warning).filter(Warning.item_id == item_id).all()
    assert len(restored_warnings) == 1
    assert restored_warnings[0].title == "Scale needs confirmation"
    assert restored_warnings[0].found == "E2.1 shows two scale labels."
    assert restored_warnings[0].why == "Measured conduit lengths may be wrong."
    assert restored_warnings[0].fix == "Select the scale that applies to this sheet."
    assert restored_warnings[0].where_ == "E2.1 title block"


def test_redoing_a_delete_removes_the_restored_item_again(db, dana, project, item):
    item_id = item.id
    review.delete_item(db, dana, item)
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()
    assert db.get(Item, item_id) is not None

    undo.redo(db, dana, project.id)
    db.flush()

    assert db.get(Item, item_id) is None


def test_undo_order_is_driven_by_seq_not_created_at(db, dana, project, sheet):
    """Two actions written in the same transaction share created_at (it's
    the transaction timestamp), so only Action.seq can tell them apart.
    Undo must reverse the more recently *assigned* action first."""
    first = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="Receptacle A",
                 system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY)
    second = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="Receptacle B",
                  system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY)
    db.add_all([first, second])
    db.flush()

    action_a = review.approve_item(db, dana, first)
    action_b = review.approve_item(db, dana, second)
    db.flush()
    # Both actions were written before any commit, so they share a
    # transaction timestamp -- created_at cannot order them.
    assert action_a.created_at == action_b.created_at
    assert action_a.seq < action_b.seq
    db.commit()

    undo.undo(db, dana, project.id)
    db.flush()
    assert second.status is ReviewStatus.READY, "the later-assigned action (B) must be undone first"
    assert first.status is ReviewStatus.APPROVED, "the earlier action (A) must still be live"

    undo.undo(db, dana, project.id)
    db.flush()
    assert first.status is ReviewStatus.READY


def test_redoing_a_scale_action_redeletes_the_restored_warning(db, dana, project, sheet):
    """The trap this function has to avoid: after undo restores the scale
    warning, redo must delete it again -- not leave the item both Ready
    to review and still carrying the warning that explained why it
    wasn't, which would be undo silently destroying evidence."""
    blocked = _blocked(db, project, sheet)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()
    assert db.query(Warning).filter(Warning.item_id == blocked.id).count() == 1

    undo.redo(db, dana, project.id)
    db.flush()

    assert blocked.status is ReviewStatus.READY
    assert sheet.scale == '1/8" = 1\'-0"'
    assert db.query(Warning).filter(Warning.item_id == blocked.id).count() == 0


def test_redo_head_is_none_before_any_undo(db, dana, project, item):
    review.approve_item(db, dana, item)
    db.flush()

    assert undo.redo_head(db, dana, project.id) is None


def test_undo_refuses_a_project_outside_the_actors_org(db, dana, project, item):
    review.approve_item(db, dana, item)
    db.flush()
    other_project = _foreign_project(db)

    with pytest.raises(CrossOrgActionError):
        undo.undo(db, dana, other_project.id)

    assert item.status is ReviewStatus.APPROVED, "a refused undo must not have touched anything"


# =========================================================================
# Fix round: findings from the Task 10 review
# =========================================================================

# --- Critical 1: undo, redo, undo bricked the project. A second undo
# after a redo must target the redo (reversing it back to the undone
# state), never the original root action again -- targeting the root a
# second time collides with the first undo's undoes_action_id under the
# partial unique index, 500s at flush, and leaves every later undo on
# the project failing identically because the root stays permanently
# "live" under the old kind-only filter. ---


def test_undo_redo_alternation_on_an_approve_action(db, dana, project, item):
    review.approve_item(db, dana, item)
    db.flush()

    undo.undo(db, dana, project.id)
    db.flush()
    assert item.status is ReviewStatus.READY

    undo.redo(db, dana, project.id)
    db.flush()
    assert item.status is ReviewStatus.APPROVED

    undo.undo(db, dana, project.id)
    db.flush()
    assert item.status is ReviewStatus.READY

    undo.redo(db, dana, project.id)
    db.flush()
    assert item.status is ReviewStatus.APPROVED


def test_undo_redo_alternation_on_a_scale_action(db, dana, project, sheet):
    blocked = _blocked(db, project, sheet)
    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    def assert_undone():
        assert sheet.scale == "mixed"
        assert blocked.status is ReviewStatus.MISSING
        assert db.query(Warning).filter(Warning.item_id == blocked.id).count() == 1

    def assert_redone():
        assert sheet.scale == '1/8" = 1\'-0"'
        assert blocked.status is ReviewStatus.READY
        assert db.query(Warning).filter(Warning.item_id == blocked.id).count() == 0

    undo.undo(db, dana, project.id)
    db.flush()
    assert_undone()

    undo.redo(db, dana, project.id)
    db.flush()
    assert_redone()

    undo.undo(db, dana, project.id)
    db.flush()
    assert_undone()

    undo.redo(db, dana, project.id)
    db.flush()
    assert_redone()


# --- Important 2: two reviewers resolving the same undo/redo target
# before either writes must surface as a 409 naming a recovery action,
# never a bare 500 from an uncaught unique-constraint violation. Forced
# deterministically: a second session genuinely performs and commits the
# first undo/redo, then this session's own head resolution is monkey-
# patched to the stale target a real race would have produced -- the
# only way to reproduce a TOCTOU window without actual concurrent
# threads. ---


def test_concurrent_undo_of_the_same_action_is_a_domain_error_not_a_500(db, dana, project, item, monkeypatch):
    action = review.approve_item(db, dana, item)
    db.flush()
    db.commit()

    other_engine = create_engine(settings.test_database_url)
    OtherSession = sessionmaker(bind=other_engine, expire_on_commit=False)
    other = OtherSession()
    try:
        other_dana = other.get(User, dana.id)
        undo.undo(other, other_dana, project.id)
        other.commit()
    finally:
        other.close()
        other_engine.dispose()

    monkeypatch.setattr(undo, "undo_head", lambda db_, actor_, project_id: action)

    with pytest.raises(DomainError) as caught:
        undo.undo(db, dana, project.id)

    assert caught.value.code == "undo_already_applied"
    assert caught.value.status == 409
    assert item.status is ReviewStatus.READY, "the other reviewer's undo must still stand"


def test_concurrent_redo_of_the_same_action_is_a_domain_error_not_a_500(db, dana, project, item, monkeypatch):
    review.approve_item(db, dana, item)
    db.flush()
    u1 = undo.undo(db, dana, project.id)
    db.commit()

    other_engine = create_engine(settings.test_database_url)
    OtherSession = sessionmaker(bind=other_engine, expire_on_commit=False)
    other = OtherSession()
    try:
        other_dana = other.get(User, dana.id)
        undo.redo(other, other_dana, project.id)
        other.commit()
    finally:
        other.close()
        other_engine.dispose()

    monkeypatch.setattr(undo, "redo_head", lambda db_, actor_, project_id: u1)

    with pytest.raises(DomainError) as caught:
        undo.redo(db, dana, project.id)

    assert caught.value.code == "redo_already_applied"
    assert caught.value.status == 409
    assert item.status is ReviewStatus.APPROVED, "the other reviewer's redo must still stand"


# --- Important 3 / also-fix: the identity-map hazard in _apply_scale's
# warning handling, and the FK-violation companion bug, for an item
# deleted out from under a scale confirmation's undo/redo. ---


def test_redoing_a_scale_action_after_the_item_was_since_deleted_does_not_raise(db, dana, project, sheet, monkeypatch):
    """If the item a scale confirmation released is later deleted
    entirely -- cascading its undo-restored warning away without telling
    the ORM -- a later redo of the scale confirmation must not treat
    that already-gone row as though it still exists: no ORM-level
    `Session.delete()` attempted against it, and no unexpected-rowcount
    warning/error from SQLAlchemy's own delete bookkeeping.

    Reproducing this needs one more ingredient than "the item was
    deleted": something has to be holding a live Python reference to the
    restored warning object across that deletion, the way ordinary
    application code would (a query result kept in a variable, a
    reviewer's screen still showing it). `Session`'s identity map holds
    *weak* references -- without something else keeping the object
    alive, Python's own garbage collector clears the identity map's
    entry before the redo ever runs, and `Session.get()` falls through
    to a real query that correctly finds nothing. An earlier version of
    this test held no such reference and passed identically whether or
    not the underlying bug was fixed; `restored_warning` below exists
    specifically to keep that reference alive and make the reproduction
    deterministic rather than a matter of GC timing.

    This is also why the failure mode observed here is an `SAWarning`
    ("DELETE statement ... expected to delete 1 row(s); 0 were matched"),
    not the `StaleDataError` an earlier read of this code path assumed:
    `Warning` carries no `version_id_col`, and SQLAlchemy's unmatched-
    DELETE check only *raises* for a versioned mapper -- for an
    unversioned one it warns and proceeds. That warning is real (visible
    in a plain `pytest -s` run's warnings summary) but unreliable to
    catch through `pytest.warns`/`recwarn` in this suite, apparently due
    to interaction with Python's per-callsite `__warningregistry__`
    dedup and pytest's own warnings-capture plugin, both nested around
    the same call -- so this test asserts by monkeypatching
    `sqlalchemy.util.warn` directly (verified to reliably intercept the
    call where the other two mechanisms did not), rather than relying on
    the warnings module's filtering.
    """
    import sqlalchemy.orm.persistence as persistence_module
    from sqlalchemy import util as sa_util

    calls = []
    monkeypatch.setattr(sa_util, "warn", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(persistence_module.util, "warn", lambda *a, **k: calls.append(a))

    blocked = _blocked(db, project, sheet)
    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()
    undo.undo(db, dana, project.id)  # restores the scale warning
    db.flush()

    # Held deliberately -- see docstring.
    restored_warning = db.query(Warning).filter(Warning.item_id == blocked.id).first()

    review.delete_item(db, dana, blocked)  # cascades the restored warning away
    db.flush()

    calls.clear()
    undo.redo(db, dana, project.id)
    db.flush()

    assert sheet.scale == '1/8" = 1\'-0"'
    assert db.get(Item, blocked.id) is None
    assert calls == [], f"expected no SQLAlchemy warning during redo, got: {calls!r}"
    assert restored_warning is not None  # keeps the reference alive through the assertions above


def test_undoing_a_scale_action_whose_item_was_since_deleted_does_not_raise(db, dana, project, sheet):
    """The companion bug in the other direction: if the item is deleted
    after set_scale() but before its scale action is undone, restoring
    the scale warning must not try to insert a Warning row pointing at
    an item id that no longer exists.
    """
    blocked = _blocked(db, project, sheet)
    scale_action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    review.delete_item(db, dana, blocked)
    db.flush()

    undo_apply.apply(db, scale_action, "before")
    db.flush()

    assert sheet.scale == "mixed"
    assert db.get(Item, blocked.id) is None
    assert db.query(Warning).filter(Warning.item_id == blocked.id).count() == 0


# --- Also-fix: the delete-undo idempotency guard returned early once
# the item existed, without independently checking its warnings, so a
# item present with its evidence missing reported success while
# restoring nothing. ---


def test_undoing_a_delete_restores_a_missing_warning_even_when_the_item_was_already_restored(db, dana, project, item):
    warning = Warning(item_id=item.id, reason=WarningReason.SCALE, title="Scale needs confirmation",
                       found="E2.1 shows two scale labels.", why="Measured conduit lengths may be wrong.",
                       fix="Select the scale that applies to this sheet.", where_="E2.1 title block")
    db.add(warning)
    db.flush()
    action = review.delete_item(db, dana, item)
    db.flush()

    undo.undo(db, dana, project.id)
    db.flush()
    assert db.get(Item, item.id) is not None

    # The item is back, but its evidence goes missing independently of
    # the item -- the exact case the early-return guard papered over.
    db.execute(delete(Warning).where(Warning.item_id == item.id))
    db.flush()

    undo_apply.apply(db, action, "before")
    db.flush()

    restored = db.query(Warning).filter(Warning.item_id == item.id).all()
    assert len(restored) == 1
    assert restored[0].title == "Scale needs confirmation"


# --- Missing coverage the review named directly ---


def test_undo_is_none_on_a_project_with_no_actions(db, dana, project):
    assert undo.undo(db, dana, project.id) is None


def test_redo_is_none_on_a_project_with_no_actions(db, dana, project):
    assert undo.redo(db, dana, project.id) is None


def test_redo_refuses_a_project_outside_the_actors_org(db, dana, project, item):
    review.approve_item(db, dana, item)
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()
    other_project = _foreign_project(db)

    with pytest.raises(CrossOrgActionError):
        undo.redo(db, dana, other_project.id)

    assert item.status is ReviewStatus.READY, "a refused redo must not have touched anything"


def test_undo_head_refuses_a_project_outside_the_actors_org(db, dana):
    other_project = _foreign_project(db)

    with pytest.raises(CrossOrgActionError):
        undo.undo_head(db, dana, other_project.id)


def test_redo_head_refuses_a_project_outside_the_actors_org(db, dana):
    other_project = _foreign_project(db)

    with pytest.raises(CrossOrgActionError):
        undo.redo_head(db, dana, other_project.id)


def test_undoing_a_scale_on_an_item_with_both_a_scale_and_legend_warning_restores_only_the_scale_warning(
    db, dana, project, sheet
):
    """scale.py's most delicate documented case: an item blocked by both
    a scale and a legend warning has only its scale warning cleared by
    set_scale() -- status stays Missing information, the legend warning
    is never touched. Undo must restore exactly what was deleted (the
    scale warning) and must never duplicate, resurrect under a new id,
    or otherwise disturb the legend warning it never removed.
    """
    item = _blocked(db, project, sheet)
    legend_warning = Warning(item_id=item.id, reason=WarningReason.LEGEND, title="Symbol not in legend",
                              found="This symbol does not appear in the E0.1 legend.",
                              why="It cannot be counted without knowing what it is.",
                              fix="Classify the symbol or confirm it against the legend.",
                              where_="E0.1 legend")
    db.add(legend_warning)
    db.flush()
    legend_warning_id = legend_warning.id

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()
    assert item.status is ReviewStatus.MISSING
    remaining = db.query(Warning).filter(Warning.item_id == item.id).all()
    assert len(remaining) == 1 and remaining[0].reason is WarningReason.LEGEND

    undo.undo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.MISSING, "set_scale() never changed this item's status in the first place"
    restored = db.query(Warning).filter(Warning.item_id == item.id).all()
    assert len(restored) == 2
    reasons = {w.reason for w in restored}
    assert reasons == {WarningReason.SCALE, WarningReason.LEGEND}
    ids = {w.id for w in restored}
    assert legend_warning_id in ids, "the legend warning must be the same row, untouched -- not recreated"
