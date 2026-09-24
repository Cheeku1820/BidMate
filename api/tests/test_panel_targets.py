"""Which rows a panel sentence would change. The router names a form --
the selection, the view, or a tag -- and this resolves it through the
same predicates the screens read from, so a proposal can never name a
row the estimator could not have reached with a filter."""

import uuid
from datetime import datetime, timezone

import pytest

from app.assistant import targets as t
from app.assistant.schemas import ScreenIn
from app.engine.conversation import RouteTargets
from app.takeoff.models import Item, ReviewStatus, Sheet


def _sheet(db, project, number="E2.1", **over):
    fields = dict(project_id=project.id, number=number, title="Power plan", discipline="Electrical",
                  revision="", scale="", scale_options=[], plan="")
    fields.update(over)
    s = Sheet(**fields)
    db.add(s); db.flush(); return s


def _item(db, project, sheet, **over):
    fields = dict(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="20A duplex receptacle",
                  system="Power", category="Devices", quantity=4, unit="EA", status=ReviewStatus.READY,
                  source_tag="R1")
    fields.update(over)
    i = Item(**fields)
    db.add(i); db.flush(); return i


def _screen(**over):
    fields = dict(name="takeoff")
    fields.update(over)
    return ScreenIn(**fields)


def test_selection_resolves_to_the_cluster_the_engine_counted(db, project):
    sheet = _sheet(db, project)
    a = _item(db, project, sheet)
    b = _item(db, project, sheet, source_tag="R1")
    other = _item(db, project, sheet, source_tag="S1", name="Single pole switch")
    out = t.resolve_items(db, project, RouteTargets(form="selection"), _screen(sheet_id=sheet.id, item_id=a.id))
    assert {i.id for i in out} == {a.id, b.id}
    assert other.id not in {i.id for i in out}


def test_selection_without_a_selected_item_resolves_to_nothing(db, project):
    sheet = _sheet(db, project)
    _item(db, project, sheet)
    assert t.resolve_items(db, project, RouteTargets(form="selection"), _screen(sheet_id=sheet.id)) == []


def test_view_resolves_to_the_sheet_and_filter_on_screen(db, project):
    sheet, other_sheet = _sheet(db, project), _sheet(db, project, number="E2.2")
    ready = _item(db, project, sheet)
    attention = _item(db, project, sheet, status=ReviewStatus.ATTENTION, source_tag="S1")
    _item(db, project, other_sheet, source_tag="T1")
    both = t.resolve_items(db, project, RouteTargets(form="view"), _screen(sheet_id=sheet.id))
    assert {i.id for i in both} == {ready.id, attention.id}
    filtered = t.resolve_items(db, project, RouteTargets(form="view"),
                               _screen(sheet_id=sheet.id, view={"filter": "attention"}))
    assert [i.id for i in filtered] == [attention.id]


def test_view_applies_the_search_the_screen_carries(db, project):
    sheet = _sheet(db, project)
    recep = _item(db, project, sheet)
    _item(db, project, sheet, name="2x4 LED troffer", source_tag="F")
    out = t.resolve_items(db, project, RouteTargets(form="view"),
                          _screen(sheet_id=sheet.id, view={"search": "duplex"}))
    assert [i.id for i in out] == [recep.id]


def test_a_tag_matches_source_tag_or_name_on_the_sheet_in_view(db, project):
    sheet, other_sheet = _sheet(db, project), _sheet(db, project, number="E2.2")
    f1 = _item(db, project, sheet, source_tag="F", name="Unclassified symbol")
    f2 = _item(db, project, sheet, source_tag="f", name="Type F fixture")
    _item(db, project, other_sheet, source_tag="F", name="Unclassified symbol")
    out = t.resolve_items(db, project, RouteTargets(form="tag", tag="F"), _screen(sheet_id=sheet.id))
    assert {i.id for i in out} == {f1.id, f2.id}
    # Stable across repeat calls: anchor_of's fallback and a proposal's
    # preview both read off this order, so it must not shuffle between
    # the answer and a later re-check of the same card.
    again = t.resolve_items(db, project, RouteTargets(form="tag", tag="F"), _screen(sheet_id=sheet.id))
    assert [i.id for i in out] == [i.id for i in again]


def test_a_rejected_item_and_a_superseded_sheet_are_never_targets(db, project):
    sheet = _sheet(db, project)
    gone = _sheet(db, project, number="E1.9", superseded_at=datetime.now(timezone.utc))
    live = _item(db, project, sheet)
    rejected = _item(db, project, sheet, source_tag="Y1", rejected_at=datetime.now(timezone.utc))
    _item(db, project, gone, source_tag="Z1")
    out = t.resolve_items(db, project, RouteTargets(form="view"), _screen(sheet_id=sheet.id))
    ids = {i.id for i in out}
    assert live.id in ids and rejected.id not in ids
    assert all(i.sheet_id == sheet.id for i in out)


def test_past_the_cap_it_refuses_rather_than_offering(db, project):
    sheet = _sheet(db, project)
    for n in range(t.MAX_TARGETS + 1):
        _item(db, project, sheet, source_tag=f"T{n}")
    with pytest.raises(t.TooMany) as raised:
        t.resolve_items(db, project, RouteTargets(form="view"), _screen(sheet_id=sheet.id))
    assert raised.value.count == t.MAX_TARGETS + 1


def test_the_anchor_is_the_selection_when_it_is_in_the_set(db, project):
    sheet = _sheet(db, project)
    a, b = _item(db, project, sheet), _item(db, project, sheet, source_tag="S1")
    assert t.anchor_of([a, b], selected_id=b.id).id == b.id
    assert t.anchor_of([a, b], selected_id=uuid.uuid4()).id == a.id
    assert t.anchor_of([], selected_id=None) is None
