"""Phase records (phases-and-timeline.md §3.1): the implicit first
phase, the one resolution, and every mutation audited and undoable
through the same action log as approve and edit. Nothing here reads
or writes a quantity or a status -- the last test says so."""
from datetime import date
from decimal import Decimal

import pytest

from app.errors import DomainError
from app.schedule import overrides
from app.schedule import phases as svc
from app.takeoff import undo
from app.takeoff.models import Action, Item, ItemLeadTime, Phase, PhaseLine, PhaseStagePlan, Sheet
from app.takeoff.totals import approved_totals


def test_no_phase_row_until_asked(db, project, dana):
    assert svc.phases_for(db, project.id) == []
    assert svc.first_phase(db, project) is None
    first = svc.first_phase(db, project, create=True)
    assert first.name == "Phase 1" and first.sort_order == 0
    assert [l.label for l in db.query(PhaseLine).filter_by(phase_id=first.id).order_by(PhaseLine.sort_order)] == \
        ["Final and daily cleanup", "Project planning, coordination and layout"]
    assert svc.first_phase(db, project, create=True).id == first.id


def test_phase_of_resolves_item_then_sheet_then_first(db, project, sheet, item, dana):
    first = svc.first_phase(db, project, create=True)
    assert svc.phase_of(item, sheet, first) == first.id
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    sheet.phase_id = second.id
    assert svc.phase_of(item, sheet, first) == second.id
    item.phase_id = first.id
    assert svc.phase_of(item, sheet, first) == first.id


def test_create_records_an_action_and_is_undoable(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    db.commit()
    action = db.query(Action).filter_by(kind="phase_create").one()
    assert action.label == "Added Phase 2"
    assert "phase_create" in undo.REVERSIBLE
    undo.undo(db, actor=dana, project_id=project.id)
    db.commit()
    assert db.get(Phase, second.id) is None
    undo.redo(db, actor=dana, project_id=project.id)
    db.commit()
    assert db.get(Phase, second.id).name == "Phase 2"
    # The template lines cascade away with the phase on undo and have to
    # come back with it on redo -- the identity map is not told about a
    # cascade, so a restore that trusts it would skip them.
    assert db.query(PhaseLine).filter_by(phase_id=second.id).count() == 2


def test_assign_sheets_moves_in_and_out_as_one_action(db, project, sheet, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    other = Sheet(project_id=project.id, number="XE-1.0", title="Power plan — phase 2", discipline="Electrical",
                  revision="", scale="", scale_options=[], plan="")
    db.add(other); db.flush()
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id, other.id])
    db.commit()
    assert sheet.phase_id == second.id and other.phase_id == second.id
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[other.id])
    db.commit()
    db.refresh(sheet)
    assert sheet.phase_id is None     # moved back to the first phase (null = first)
    action = db.query(Action).filter_by(kind="sheet_phase_set").order_by(Action.seq.desc()).first()
    assert str(sheet.id) in action.before["sheets"]
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(sheet)
    assert sheet.phase_id == second.id


def test_delete_moves_sheets_and_overrides_and_undoes_in_one_press(db, project, sheet, item, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id])
    svc.set_item_phase(db, actor=dana, item=item, phase_id=second.id)
    db.commit()
    svc.delete_phase(db, actor=dana, phase=second)
    db.commit()
    db.refresh(sheet); db.refresh(item)
    assert sheet.phase_id == first.id and item.phase_id is None
    undo.undo(db, actor=dana, project_id=project.id); db.commit()
    db.refresh(sheet); db.refresh(item)
    restored = db.get(Phase, second.id)
    assert restored is not None and restored.name == "Phase 2"
    assert sheet.phase_id == second.id and item.phase_id == second.id


def test_the_last_phase_cannot_be_deleted(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    with pytest.raises(DomainError) as e:
        svc.delete_phase(db, actor=dana, phase=first)
    assert e.value.code == "last_phase"
    assert e.value.status == 409


def test_phases_change_no_total(db, project, sheet, item, dana):
    before = approved_totals(db, project.id)
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id])
    db.commit()
    assert approved_totals(db, project.id) == before


# --- Every kind, both directions ---


def _order(db, project):
    return [p.id for p in svc.phases_for(db, project.id)]


def test_replaying_creates_restores_the_order_they_changed(db, project, dana):
    """Three phases created after the first, each shifting the others up;
    two undos then two redos have to land every phase back where it
    was, or the deferred uq_phase_order fails at commit -- long after
    the flush, as a 500."""
    first = svc.first_phase(db, project, create=True)
    p2 = svc.create_phase(db, actor=dana, project=project, name="P2", after_phase_id=first.id)
    p3 = svc.create_phase(db, actor=dana, project=project, name="P3", after_phase_id=first.id)
    p4 = svc.create_phase(db, actor=dana, project=project, name="P4", after_phase_id=first.id)
    db.commit()
    assert _order(db, project) == [first.id, p4.id, p3.id, p2.id]
    undo.undo(db, actor=dana, project_id=project.id); db.commit()
    undo.undo(db, actor=dana, project_id=project.id); db.commit()
    assert _order(db, project) == [first.id, p2.id]
    undo.redo(db, actor=dana, project_id=project.id); db.commit()
    undo.redo(db, actor=dana, project_id=project.id); db.commit()
    db.expire_all()
    assert _order(db, project) == [first.id, p4.id, p3.id, p2.id]
    assert [p.sort_order for p in svc.phases_for(db, project.id)] == [0, 1, 2, 3]


def test_edit_is_undoable_and_redoable(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.edit_phase(db, actor=dana, phase=second,
                   changes={"name": "Area B", "start_date": date(2026, 10, 1), "notes": None})
    db.commit()
    assert (second.name, second.start_date, second.notes) == ("Area B", date(2026, 10, 1), "")
    assert db.query(Action).filter_by(kind="phase_edit").one().label == "Renamed Phase 2 to Area B"
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(second)
    assert (second.name, second.start_date) == ("Phase 2", None)
    undo.redo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(second)
    assert (second.name, second.start_date) == ("Area B", date(2026, 10, 1))


def test_edit_labels_a_notes_only_change_and_refuses_an_empty_name(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    svc.edit_phase(db, actor=dana, phase=first, changes={"notes": "Existing to remain on the west wing"})
    assert db.query(Action).filter_by(kind="phase_edit").one().label == "Changed notes on Phase 1"
    svc.edit_phase(db, actor=dana, phase=first, changes={"required_finish_date": date(2027, 1, 15)})
    assert db.query(Action).filter_by(kind="phase_edit").order_by(Action.seq.desc()).first().label == "Changed dates on Phase 1"
    with pytest.raises(DomainError) as e:
        svc.edit_phase(db, actor=dana, phase=first, changes={"name": "   "})
    assert e.value.code == "phase_name_needed"
    with pytest.raises(DomainError) as e:
        svc.edit_phase(db, actor=dana, phase=first, changes={"sort_order": 3})
    assert e.value.code == "no_changes_to_apply"


def test_reorder_is_undoable_and_redoable_and_refuses_a_no_op(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.reorder_phase(db, actor=dana, phase=second, sort_order=0)
    db.commit()
    assert _order(db, project) == [second.id, first.id]
    with pytest.raises(DomainError) as e:
        svc.reorder_phase(db, actor=dana, phase=second, sort_order=0)
    assert e.value.code == "no_changes_to_apply"
    undo.undo(db, actor=dana, project_id=project.id); db.commit()
    assert _order(db, project) == [first.id, second.id]
    undo.redo(db, actor=dana, project_id=project.id); db.commit()
    assert _order(db, project) == [second.id, first.id]


def test_delete_is_redoable(db, project, sheet, item, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id])
    svc.set_item_phase(db, actor=dana, item=item, phase_id=second.id)
    svc.delete_phase(db, actor=dana, phase=second)
    db.commit()
    undo.undo(db, actor=dana, project_id=project.id); db.commit()
    assert db.get(Phase, second.id) is not None
    undo.redo(db, actor=dana, project_id=project.id); db.commit()
    db.refresh(sheet); db.refresh(item)
    assert db.get(Phase, second.id) is None
    assert sheet.phase_id == first.id and item.phase_id is None
    assert _order(db, project) == [first.id]


def test_deleting_the_first_phase_promotes_the_next_and_replays(db, project, sheet, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    db.commit()
    assert sheet.phase_id is None  # on the first phase, written as null
    svc.delete_phase(db, actor=dana, phase=first)
    db.commit()
    db.refresh(sheet)
    assert _order(db, project) == [second.id]
    assert svc.phases_for(db, project.id)[0].sort_order == 0
    assert sheet.phase_id is None and svc.phase_of(Item(), sheet, svc.first_phase(db, project)) == second.id
    undo.undo(db, actor=dana, project_id=project.id); db.commit()
    assert _order(db, project) == [first.id, second.id]
    undo.redo(db, actor=dana, project_id=project.id); db.commit()
    assert _order(db, project) == [second.id]


def test_item_phase_set_is_undoable_and_redoable(db, project, sheet, item, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.set_item_phase(db, actor=dana, item=item, phase_id=second.id)
    db.commit()
    assert db.query(Action).filter_by(kind="item_phase_set").one().label == "Moved 20A duplex receptacle to Phase 2"
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(item)
    assert item.phase_id is None
    undo.redo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(item)
    assert item.phase_id == second.id
    svc.set_item_phase(db, actor=dana, item=item, phase_id=None)
    db.commit()
    assert item.phase_id is None


def test_item_phase_set_undo_on_a_deleted_item_is_a_domain_error(db, project, sheet, item, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.set_item_phase(db, actor=dana, item=item, phase_id=second.id)
    db.commit()
    db.delete(item); db.commit()
    with pytest.raises(DomainError) as e:
        undo.undo(db, actor=dana, project_id=project.id)
    assert e.value.code == "item_no_longer_exists" and e.value.status == 409


def test_assign_sheets_treats_null_and_the_first_phase_as_one_place(db, project, sheet, dana):
    first = svc.first_phase(db, project, create=True)
    with pytest.raises(DomainError) as e:
        svc.assign_sheets(db, actor=dana, phase=first, sheet_ids=[sheet.id])
    assert e.value.code == "no_changes_to_apply"
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id])
    db.commit()
    # Assigning the first phase's full set: the sheet comes back as null,
    # and that is the only change recorded.
    svc.assign_sheets(db, actor=dana, phase=first, sheet_ids=[sheet.id])
    db.commit()
    db.refresh(sheet)
    assert sheet.phase_id is None
    action = db.query(Action).filter_by(kind="sheet_phase_set").order_by(Action.seq.desc()).first()
    assert action.before["sheets"] == {str(sheet.id): str(second.id)}
    assert action.after["sheets"] == {str(sheet.id): None}
    # Removing it from the first phase's set is not a move anywhere.
    with pytest.raises(DomainError) as e:
        svc.assign_sheets(db, actor=dana, phase=first, sheet_ids=[])
    assert e.value.code == "no_changes_to_apply"


def test_create_snapshots_who_set_each_line(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    action = db.query(Action).filter_by(kind="phase_create").one()
    assert all("updated_by_user_id" in line for line in action.after["lines"])
    assert action.before["order"] == [str(first.id)]
    assert len(action.after["order"]) == 2


def test_line_hours_override_and_reset(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    line = db.query(PhaseLine).filter_by(phase_id=first.id).order_by(PhaseLine.sort_order).first()
    overrides.set_line_hours(db, actor=dana, line=line, hours=Decimal("12"))
    db.commit()
    assert line.hours_override == Decimal("12.00")
    overrides.set_line_hours(db, actor=dana, line=line, hours=None)
    db.commit()
    assert line.hours_override is None
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(line)
    assert line.hours_override == Decimal("12.00")


def test_stage_plan_is_sparse_and_clears_per_field(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    row = overrides.set_stage_plan(db, actor=dana, phase=first, stage="rough_in", changes={"journeyman": 4, "start_date": date(2026, 10, 19)})
    db.commit()
    assert row.journeyman == 4 and row.foreman is None
    overrides.set_stage_plan(db, actor=dana, phase=first, stage="rough_in", changes={"journeyman": None})
    db.commit(); db.refresh(row)
    assert row.journeyman is None and row.start_date == date(2026, 10, 19)
    with pytest.raises(DomainError):
        overrides.set_stage_plan(db, actor=dana, phase=first, stage="painting", changes={"journeyman": 1})


def test_lead_time_needs_a_source_and_clears_together(db, project, item, dana):
    with pytest.raises(DomainError) as e:
        overrides.set_lead_time(db, actor=dana, item=item, changes={"lead_weeks": 40}, today=date(2026, 9, 21))
    assert e.value.code == "lead_time_source_needed"
    row = overrides.set_lead_time(db, actor=dana, item=item, changes={"lead_weeks": 40, "source_label": "Eaton rep"}, today=date(2026, 9, 21))
    db.commit()
    assert (row.source, row.quoted_at, row.flagged) == ("estimator", date(2026, 9, 21), True)
    overrides.set_lead_time(db, actor=dana, item=item, changes={"lead_weeks": None}, today=date(2026, 9, 21))
    db.commit(); db.refresh(row)
    assert row.lead_weeks is None and row.source is None and row.source_label == "" and row.quoted_at is None
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(row)
    assert row.lead_weeks == 40 and row.source_label == "Eaton rep"


def test_unflag_keeps_the_row_but_hides_it(db, project, item, dana):
    row = overrides.set_lead_time(db, actor=dana, item=item, changes={"flagged": False}, today=date(2026, 9, 21))
    db.commit()
    assert row.flagged is False


def test_phase_line_edit_undo_survives_a_cascade(db, project, dana):
    """PhaseLine cascades with its phase at the DB level only (ON DELETE
    CASCADE FK, never an ORM relationship) -- deleting the Phase row
    directly, so the ORM's own delete-tracking never touches PhaseLine
    at all. Combined with this session's expire_on_commit=False, `line`'s
    identity-mapped object stays a live-looking Python instance here
    even though its row is gone: exactly the trap db.get() falls into,
    and the one _get_or_expunge/_exists helpers exist elsewhere to avoid.
    apply_undo must re-query rather than trust db.get()'s identity-map
    fast path for this row."""
    from sqlalchemy import delete as sa_delete

    first = svc.first_phase(db, project, create=True)
    line = db.query(PhaseLine).filter_by(phase_id=first.id).order_by(PhaseLine.sort_order).first()
    line_id = line.id
    overrides.set_line_hours(db, actor=dana, line=line, hours=Decimal("12"))
    db.commit()
    # Delete the phase by a raw statement, not svc.delete_phase() or
    # db.delete() -- so nothing tells the ORM that phase_lines cascaded
    # away underneath it. `line` stays in the identity map, unexpired.
    db.execute(sa_delete(Phase).where(Phase.id == first.id))
    db.commit()
    undo.undo(db, actor=dana, project_id=project.id)
    db.commit()
    # A real query never finds the row either way.
    assert db.query(PhaseLine).filter_by(id=line_id).one_or_none() is None
    # The stale in-memory object must be left alone -- never silently
    # rewritten (and flushed) to describe a row that no longer exists.
    assert line.hours_override == Decimal("12.00")


def test_lead_time_label_without_weeks_is_refused(db, project, item, dana):
    with pytest.raises(DomainError) as e:
        overrides.set_lead_time(db, actor=dana, item=item, changes={"source_label": "Eaton rep"}, today=date(2026, 9, 21))
    assert e.value.code == "lead_time_weeks_needed"


def test_lead_time_quoted_at_without_weeks_is_refused(db, project, item, dana):
    overrides.set_lead_time(db, actor=dana, item=item, changes={"flagged": False}, today=date(2026, 9, 21))
    db.commit()
    with pytest.raises(DomainError) as e:
        overrides.set_lead_time(db, actor=dana, item=item, changes={"quoted_at": date(2026, 1, 1)}, today=date(2026, 9, 21))
    assert e.value.code == "lead_time_weeks_needed"


def test_lead_time_no_op_is_refused_and_not_recorded(db, project, item, dana):
    overrides.set_lead_time(db, actor=dana, item=item, changes={"needed_for_stage": "trim"}, today=date(2026, 9, 21))
    db.commit()
    with pytest.raises(DomainError) as e:
        overrides.set_lead_time(db, actor=dana, item=item, changes={"needed_for_stage": "trim"}, today=date(2026, 9, 21))
    assert e.value.code == "no_changes_to_apply"
    db.commit()
    assert db.query(Action).filter_by(kind="lead_time_edit").count() == 1


def test_stage_plan_undo_restores_who_set_it(db, project, org, dana):
    from app.auth.passwords import hash_password
    from app.identity.models import User

    other = User(org_id=org.id, email="sam@example.com", password_hash=hash_password("correct-horse"),
                 name="Sam Ortiz", color="#7a4b8f")
    db.add(other); db.flush()
    first = svc.first_phase(db, project, create=True)
    row = overrides.set_stage_plan(db, actor=dana, phase=first, stage="rough_in", changes={"journeyman": 4})
    db.commit()
    assert row.updated_by_user_id == dana.id
    overrides.set_stage_plan(db, actor=other, phase=first, stage="rough_in", changes={"journeyman": 6})
    db.commit()
    assert row.updated_by_user_id == other.id
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(row)
    assert row.journeyman == 4 and row.updated_by_user_id == dana.id
