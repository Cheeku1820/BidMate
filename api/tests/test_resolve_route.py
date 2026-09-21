"""POST /api/items/{id}/resolve -- proposes, never writes."""
import pytest
from sqlalchemy import select

from app.engine import resolve as engine_resolve
from app.takeoff.models import Action, Item, ReviewStatus


def _sibling(db, item, tag="F", sheet=None, name="Luminaire type F"):
    twin = Item(project_id=item.project_id, sheet_id=(sheet or item).sheet_id if sheet is None else sheet.id,
                symbol="luminaire", name=name, system="Lighting", category="Fixtures", quantity=1, unit="EA",
                status=ReviewStatus.ATTENTION, x=10, y=10, source_tag=tag)
    db.add(twin); db.flush(); return twin


@pytest.fixture
def stub_model(monkeypatch):
    calls = []
    monkeypatch.setattr(engine_resolve.llm, "available", lambda: True)
    def fake(text, item_ctx, candidates, schedule_text):
        calls.append({"text": text, "ctx": item_ctx, "candidates": candidates, "schedule": schedule_text})
        return {"name": "2x4 LED troffer, 4000K — type F", "system": "Lighting", "category": "Fixtures", "unit": "ea",
                "catalog_id": None, "schedule_match": {"sheet": "E-501", "line": "F"}, "quantity": None,
                "summary": "Applies to all 3 · renames Luminaire type F · clears the warning"}
    monkeypatch.setattr(engine_resolve.llm, "resolve_proposal", fake)
    return calls


def test_reclassify_calls_the_model_once_and_targets_the_cluster(client, db, item, signed_in_user, stub_model):
    # The conftest item's quantity (14) is unrelated to cluster size --
    # set it to 1 so the three-row cluster sums to 3, matching how the
    # engine actually lands one row per (sheet, source_tag) cluster with
    # quantity = placement count (engine/rows.py, merge.py).
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION; item.quantity = 1
    a = _sibling(db, item); b = _sibling(db, item); db.commit()
    r = client.post(f"/api/items/{item.id}/resolve", json={"text": "2x4 LED troffer, type F on E-501"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "reclassify" and body["source"] == "read"
    assert set(body["target_item_ids"]) == {str(item.id), str(a.id), str(b.id)}
    assert set(body["versions"]) == set(body["target_item_ids"])
    assert body["schedule_match"] == {"sheet": "E-501", "line": "F"}
    assert len(stub_model) == 1 and stub_model[0]["ctx"]["tag"] == "F" and stub_model[0]["ctx"]["count"] == 3


def test_resolve_writes_nothing(client, db, item, signed_in_user, stub_model):
    before_name = item.name
    client.post(f"/api/items/{item.id}/resolve", json={"text": "2x4 LED troffer"})
    db.expire_all()
    assert db.get(Item, item.id).name == before_name
    assert db.scalars(select(Action)).first() is None


def test_exclusion_never_reaches_the_model(client, db, item, signed_in_user, monkeypatch):
    monkeypatch.setattr(engine_resolve.llm, "available", lambda: True)
    def must_not(*a, **k):
        raise AssertionError("the model was asked whether to reject")
    monkeypatch.setattr(engine_resolve.llm, "resolve_proposal", must_not)
    r = client.post(f"/api/items/{item.id}/resolve", json={"text": "not a device, it's the TOP OF ATRIUM label"})
    body = r.json()
    assert body["intent"] == "exclude"
    assert body["reject_reason"] == "not a device, it's the TOP OF ATRIUM label"
    assert body["target_item_ids"] == [str(item.id)]


def test_count_is_the_placement_count_not_the_row_count(client, db, item, signed_in_user, stub_model):
    """The engine lands one row per (sheet, source_tag) cluster with
    quantity = the placement count it counted (engine/rows.py,
    merge.py) -- a tag counted 30 times is one row with quantity 30, so
    `count` must read that field, not len(targets). Exercised as a
    single-item cluster (untagged item fixture), the exact case the
    earlier len(targets) bug always got right by accident, since
    len(targets) == 1 there too -- only the summed quantity tells the
    two apart."""
    item.quantity = 30; db.commit()
    r = client.post(f"/api/items/{item.id}/resolve", json={"text": "junction box"})
    assert r.json()["intent"] == "reclassify"
    assert stub_model[0]["ctx"]["count"] == 30

    r2 = client.post(f"/api/items/{item.id}/resolve", json={"text": "not a device"})
    assert r2.json()["summary"] == "Reject 30 — not a device"


@pytest.mark.parametrize("sentence", ["counter height duplex receptacle", "ceiling mounted occupancy sensor",
                                      "surface mounting box", "480 voltage disconnect"])
def test_a_device_name_in_context_vocabulary_still_reaches_classification(client, db, item, signed_in_user, stub_model, sentence):
    """The panel router reads "ceiling", "height", "mounting", "voltage"
    as project context. On this route the estimator was asked what the
    item is, so a sentence with those words is a device name and must
    produce a named proposal, never "Couldn't read that"."""
    body = client.post(f"/api/items/{item.id}/resolve", json={"text": sentence}).json()
    assert body["intent"] == "reclassify", body
    assert body["name"] == "2x4 LED troffer, 4000K — type F"
    assert len(stub_model) == 1 and stub_model[0]["text"] == sentence


@pytest.mark.parametrize("sentence", ["counter height duplex receptacle", "ceiling mounted occupancy sensor"])
def test_a_device_name_in_context_vocabulary_is_named_on_the_typed_path_too(client, db, item, signed_in_user, monkeypatch, sentence):
    monkeypatch.setattr(engine_resolve.llm, "available", lambda: False)
    body = client.post(f"/api/items/{item.id}/resolve", json={"text": sentence}).json()
    assert body["intent"] == "reclassify" and body["source"] == "typed"
    assert body["name"] == sentence


def test_empty_text_is_unknown(client, item, signed_in_user, stub_model):
    body = client.post(f"/api/items/{item.id}/resolve", json={"text": "   "}).json()
    assert body["intent"] == "unknown" and not stub_model


def test_an_untagged_item_targets_itself_only(client, db, item, signed_in_user, stub_model):
    item.source_tag = ""; db.commit()
    body = client.post(f"/api/items/{item.id}/resolve", json={"text": "junction box"}).json()
    assert body["target_item_ids"] == [str(item.id)]


def test_same_tag_on_another_sheet_is_not_a_target(client, db, item, sheet, project, signed_in_user, stub_model):
    from app.takeoff.models import Sheet
    other = Sheet(project_id=project.id, number="EL101", title="Lighting", discipline="Electrical", revision="",
                  scale="", scale_options=[], plan="", takeoff_id="d", page_index=7)
    db.add(other); db.flush()
    item.source_tag = "F"
    elsewhere = _sibling(db, item, sheet=other); db.commit()
    body = client.post(f"/api/items/{item.id}/resolve", json={"text": "2x4 LED troffer"}).json()
    assert str(elsewhere.id) not in body["target_item_ids"]


def test_no_key_gives_the_typed_proposal(client, db, item, signed_in_user, monkeypatch):
    monkeypatch.setattr(engine_resolve.llm, "available", lambda: False)
    body = client.post(f"/api/items/{item.id}/resolve", json={"text": "28 patient headwalls"}).json()
    assert body["source"] == "typed" and body["name"] == "patient headwalls" and body["quantity"] == 28
    assert body["catalog_id"] is None


def test_schedule_text_cannot_set_a_quantity(client, db, item, signed_in_user, monkeypatch):
    """ROADMAP invariant 11: drawing text is data. The stub echoes back
    what the route sent it; the schedule block must be quoted data and
    the quantity must come only from the sentence."""
    monkeypatch.setattr(engine_resolve.llm, "available", lambda: True)
    seen = {}
    def fake(text, item_ctx, candidates, schedule_text):
        seen["schedule"] = schedule_text
        return {"name": "duplex receptacle", "system": "Power", "category": "Devices", "unit": "ea",
                "catalog_id": None, "schedule_match": None, "quantity": None, "summary": "Renames 1 item"}
    monkeypatch.setattr(engine_resolve.llm, "resolve_proposal", fake)
    body = client.post(f"/api/items/{item.id}/resolve", json={"text": "duplex receptacle"}).json()
    assert body["quantity"] is None
    assert "approve" not in body["summary"].lower()
