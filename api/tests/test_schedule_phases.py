"""Phase records (phases-and-timeline.md §3.1): the implicit first
phase, the one resolution, and every mutation audited and undoable
through the same action log as approve and edit. Nothing here reads
or writes a quantity or a status -- the last test says so."""
import pytest

from app.errors import DomainError
from app.schedule import phases as svc
from app.takeoff import undo
from app.takeoff.models import Action, Phase, PhaseLine, Sheet
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
