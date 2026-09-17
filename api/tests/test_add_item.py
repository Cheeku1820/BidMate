"""An item a person adds (from a symbol match) is one undoable `add`
action: undo removes it and its warning, redo brings both back."""
import pytest
from sqlalchemy import select

from app.errors import DomainError
from app.takeoff import review, undo
from app.takeoff.models import Item, Project, Warning


def _warning():
    return {"reason": "legend", "title": "Symbol not in legend", "found": "A symbol appears 3 times on E2.1 but isn't in the legend.",
            "why": "An unclassified symbol has no catalog item, so it isn't counted or priced yet.",
            "fix": "Assign a classification, or reject it if it isn't a device.", "where": "E2.1."}


def test_add_item_is_one_reversible_action(db, project, sheet, dana):
    item, action = review.add_item(
        db, dana, project=project, sheet=sheet, name="Unclassified symbol", symbol="generic", system="Unknown",
        quantity=3, placements=[[100, 100, 8, 8], [200, 100, 8, 8], [300, 100, 8, 8]], x=100, y=100,
        source_tag="match:abc", status="attention", warning=_warning(), label="Added 3 symbols from a drawn symbol")
    db.commit()
    assert action.kind == "add" and action.item_id == item.id and action.before == {}
    assert db.scalar(select(Warning).where(Warning.item_id == item.id)) is not None
    assert undo.undo_head(db, dana, project.id).id == action.id

    undo.undo(db, dana, project.id); db.commit()
    assert db.get(Item, item.id) is None
    assert db.scalar(select(Warning).where(Warning.item_id == item.id)) is None

    undo.redo(db, dana, project.id); db.commit()
    restored = db.get(Item, item.id)
    assert restored is not None and restored.quantity == 3 and restored.source_tag == "match:abc"
    assert db.scalar(select(Warning).where(Warning.item_id == item.id)) is not None


def test_a_named_item_lands_ready_without_a_warning(db, project, sheet, dana):
    item, _ = review.add_item(
        db, dana, project=project, sheet=sheet, name="Duplex receptacle", symbol="receptacle", system="Power",
        quantity=2, placements=[[100, 100, 8, 8], [200, 100, 8, 8]], x=100, y=100,
        source_tag="match:def", status="ready", warning=None, label="Added 2 duplex receptacles from a drawn symbol")
    db.commit()
    assert item.status.value == "ready" and db.scalar(select(Warning).where(Warning.item_id == item.id)) is None


def _add(db, dana, project, sheet, *, status, warning, sheet_project=None):
    return review.add_item(
        db, dana, project=sheet_project or project, sheet=sheet, name="Duplex receptacle", symbol="receptacle",
        system="Power", quantity=1, placements=[[100, 100, 8, 8]], x=100, y=100,
        source_tag="match:refused", status=status, warning=warning, label="Added")


def test_add_item_refuses_a_status_other_than_ready_or_attention(db, project, sheet, dana):
    with pytest.raises(DomainError) as exc:
        _add(db, dana, project, sheet, status="approved", warning=None)
    assert exc.value.code == "invalid_status" and exc.value.status == 422
    assert db.scalar(select(Item).where(Item.source_tag == "match:refused")) is None


def test_add_item_with_attention_status_requires_a_warning(db, project, sheet, dana):
    with pytest.raises(DomainError) as exc:
        _add(db, dana, project, sheet, status="attention", warning=None)
    assert exc.value.code == "warning_required" and exc.value.status == 422
    assert db.scalar(select(Item).where(Item.source_tag == "match:refused")) is None


def test_add_item_with_ready_status_refuses_a_warning(db, project, sheet, dana):
    with pytest.raises(DomainError) as exc:
        _add(db, dana, project, sheet, status="ready", warning=_warning())
    assert exc.value.code == "warning_not_allowed" and exc.value.status == 422
    assert db.scalar(select(Item).where(Item.source_tag == "match:refused")) is None


def test_add_item_refuses_a_sheet_from_a_different_project(db, project, sheet, dana):
    other = Project(org_id=project.org_id, name="A different project", revision_set_label="")
    db.add(other)
    db.flush()
    with pytest.raises(DomainError) as exc:
        _add(db, dana, project, sheet, status="ready", warning=None, sheet_project=other)
    assert exc.value.code == "sheet_not_in_project" and exc.value.status == 404
    assert db.scalar(select(Item).where(Item.source_tag == "match:refused")) is None
