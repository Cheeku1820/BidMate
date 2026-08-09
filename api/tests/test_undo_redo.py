from decimal import Decimal

import pytest

from app.takeoff import bulk, review, scale as scale_module, undo
from app.takeoff.actions import CrossOrgActionError
from app.takeoff.models import Action, Item, ReviewStatus, Warning, WarningReason


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


def test_undo_head_is_none_on_a_project_with_no_actions(db, project):
    assert undo.undo_head(db, project.id) is None


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

    assert undo.redo_head(db, project.id) is None


def test_undo_refuses_a_project_outside_the_actors_org(db, dana, project, item, org):
    from app.identity.models import Org
    from app.takeoff.models import Project as ProjectModel

    review.approve_item(db, dana, item)
    db.flush()

    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = ProjectModel(org_id=other_org.id, name="A different firm's project")
    db.add(other_project)
    db.flush()

    with pytest.raises(CrossOrgActionError):
        undo.undo(db, dana, other_project.id)

    assert item.status is ReviewStatus.APPROVED, "a refused undo must not have touched anything"
