"""A routed sentence becomes one typed proposal -- or nothing. Every id
in it was resolved from the project's own rows; every field belongs to
the kind's own endpoint; nothing names how it was produced."""

import json
import uuid

import pytest

from app.assistant import propose
from app.assistant.schemas import ScreenIn
from app.engine.conversation import Route, RouteTargets
from app.plan import service as plan_service
from app.takeoff.models import Document, Item, ReviewStatus, ScopeStatement, Sheet


def _sheet(db, project, number="E2.1"):
    s = Sheet(project_id=project.id, number=number, title="Power plan", discipline="Electrical",
              revision="", scale="", scale_options=[], plan="")
    db.add(s); db.flush(); return s


def _item(db, project, sheet, **over):
    fields = dict(project_id=project.id, sheet_id=sheet.id, symbol="unknown", name="Unclassified symbol",
                  system="Unknown", category="Unclassified", quantity=6, unit="EA",
                  status=ReviewStatus.ATTENTION, source_tag="F")
    fields.update(over)
    i = Item(**fields)
    db.add(i); db.flush(); return i


def _scope(db, project, dana):
    d = Document(project_id=project.id, filename="scope.pdf", doc_type="Scope", content_type="application/pdf",
                 size_bytes=1, sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id, status="processed")
    db.add(d); db.flush()
    s = ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=1,
                       kind="excluded", text="Site lighting.", quote="- Site lighting.", status="found",
                       run_id=uuid.uuid4())
    db.add(s); db.flush(); return s


def _screen(**over):
    fields = dict(name="takeoff")
    fields.update(over)
    return ScreenIn(**fields)


def _route(intent, form="selection", **kw):
    return Route(intent=intent,
                 targets=RouteTargets(form=form, tag=kw.pop("tag", ""), record_key=kw.pop("record_key", "")),
                 field=kw.pop("field", ""), value=kw.pop("value", ""))


def _resolved(items, **over):
    first = items[0]
    out = {"intent": "reclassify", "target_item_ids": [i.id for i in items],
           "versions": {i.id: i.version for i in items},
           "name": "2x4 LED troffer, type F", "system": "Lighting", "category": "Fixtures", "unit": "ea",
           "catalog_id": None, "schedule_match": None, "quantity": None, "reject_reason": None,
           "summary": "Name the cluster.", "source": "read"}
    out.update(over)
    return out


def test_unknown_and_empty_target_sets_propose_nothing(db, project):
    sheet = _sheet(db, project)
    _item(db, project, sheet)
    assert propose.build(db, project=project, route=_route("unknown", form="none"), screen=_screen(),
                         message="what is here?") is None
    assert propose.build(db, project=project, route=_route("reclassify"), screen=_screen(sheet_id=sheet.id),
                         message="these are type F") is None


def test_a_reclassify_calls_the_classifier_once_and_never_approves(db, project, monkeypatch):
    sheet = _sheet(db, project)
    a, b = _item(db, project, sheet), _item(db, project, sheet)
    calls = []

    def fake(db_, item, text, *, cluster=True):
        calls.append((item.id, text, cluster))
        return _resolved([a, b])

    monkeypatch.setattr(propose.resolve_service, "resolve_for_item", fake)
    out = propose.build(db, project=project, route=_route("reclassify", field="classification"),
                        screen=_screen(sheet_id=sheet.id, item_id=a.id),
                        message="these are all 2x4 LED troffers, type F")
    assert len(calls) == 1 and calls[0][0] == a.id and calls[0][2] is True
    assert out["kind"] == "item" and out["approve"] is False
    assert out["proposal"]["name"] == "2x4 LED troffer, type F"
    assert out["proposal"]["target_item_ids"] == [str(a.id), str(b.id)]
    assert out["count"] == 2 and out["sheet_number"] == "E2.1" and out["item_id"] == str(a.id)
    assert out["note"] == "Approving stays with you."
    assert len(out["targets_preview"]) == 2 and out["more_count"] == 0


def test_a_tag_form_reclassify_stays_within_the_anchors_cluster(db, project, monkeypatch):
    sheet = _sheet(db, project)
    f1a = _item(db, project, sheet, source_tag="F1", name="Type F recessed")
    f1b = _item(db, project, sheet, source_tag="F1", name="Type F recessed")
    f2a = _item(db, project, sheet, source_tag="F2", name="Type F pendant")

    def fake(db_, item, text, *, cluster=True):
        cluster_items = [i for i in (f1a, f1b, f2a) if i.source_tag == item.source_tag]
        return _resolved(cluster_items)

    monkeypatch.setattr(propose.resolve_service, "resolve_for_item", fake)
    out = propose.build(db, project=project, route=_route("reclassify", form="tag", tag="type f"),
                        screen=_screen(sheet_id=sheet.id, item_id=f1a.id),
                        message="these are all type F recessed")
    assert out["proposal"]["target_item_ids"] == [str(f1a.id), str(f1b.id)]
    assert out["count"] == 2
    assert len(out["targets_preview"]) == 2
    assert "sit outside this cluster" in out["summary"]
    assert "1 other matching item" in out["summary"]


def test_a_view_form_reclassify_matches_one_cluster_exactly(db, project, monkeypatch):
    sheet = _sheet(db, project)
    a = _item(db, project, sheet, source_tag="F1")
    b = _item(db, project, sheet, source_tag="F1")

    monkeypatch.setattr(propose.resolve_service, "resolve_for_item",
                        lambda db_, item, text, *, cluster=True: _resolved([a, b]))
    out = propose.build(db, project=project, route=_route("reclassify", form="view"),
                        screen=_screen(sheet_id=sheet.id), message="these are all type F")
    assert out["proposal"]["target_item_ids"] == [str(a.id), str(b.id)]
    assert out["count"] == 2
    assert "sit outside this cluster" not in out["summary"]


def test_an_exclude_carries_the_sentence_as_the_reason(db, project, monkeypatch):
    sheet = _sheet(db, project)
    a = _item(db, project, sheet)
    monkeypatch.setattr(propose.resolve_service, "resolve_for_item",
                        lambda db_, item, text, *, cluster=True: _resolved([a], intent="exclude", reject_reason=text))
    out = propose.build(db, project=project, route=_route("exclude"),
                        screen=_screen(sheet_id=sheet.id, item_id=a.id),
                        message="ignore this wing, it's existing to remain")
    assert out["kind"] == "item" and out["proposal"]["intent"] == "exclude"
    assert out["proposal"]["reject_reason"].startswith("ignore this wing")
    assert "out of the takeoff" in out["summary"]


def test_a_context_sentence_becomes_a_note_with_no_model_call(db, project, monkeypatch):
    def _must_not_call(*args, **kwargs):
        raise AssertionError("the note path must not call the classifier")

    monkeypatch.setattr(propose.resolve_service, "resolve_for_item", _must_not_call)
    out = propose.build(db, project=project,
                        route=_route("set_context", form="none", field="text",
                                     value="Ceiling is 14 feet in the warehouse."),
                        screen=_screen(name="notes"), message="Ceiling is 14 feet in the warehouse.")
    assert out["kind"] == "note" and out["usage"] == "context"
    assert out["body"] == "Ceiling is 14 feet in the warehouse."
    assert out["title"] == "Ceiling is 14 feet in the warehouse" and len(out["title"]) <= 300
    assert out["category"] == "existing_condition"


def test_a_scope_decision_names_the_statement_and_its_current_words(db, project, dana):
    statement = _scope(db, project, dana)
    out = propose.build(db, project=project,
                        route=_route("decide_scope", form="record", record_key=f"scope:{statement.id}",
                                     field="status", value="confirmed"),
                        screen=_screen(name="confirm"), message="site lighting is by others, that's right")
    assert out["kind"] == "scope" and out["statement_id"] == str(statement.id)
    assert out["status"] == "confirmed" and out["current_text"] == "Site lighting."
    assert out["quote"] == "- Site lighting." and "Confirm this scope statement" in out["summary"]


def test_a_scope_correction_carries_edited_text_instead_of_a_status(db, project, dana):
    statement = _scope(db, project, dana)
    out = propose.build(db, project=project,
                        route=_route("decide_scope", form="record", record_key=f"scope:{statement.id}",
                                     field="text", value="Site lighting excluded; pole bases by the GC."),
                        screen=_screen(name="confirm"), message="say pole bases are by the GC")
    assert out["kind"] == "scope" and out["edited_text"].startswith("Site lighting excluded")
    assert out.get("status") is None


def test_a_faked_routing_call_produces_a_scope_proposal_with_the_decision_word(db, project, dana, monkeypatch):
    """End to end, through the real language boundary rather than a
    hand-built Route: `llm.route_message` is faked, `conversation.
    route_message` routes it, and the result is handed to `propose.build`
    exactly as `service.propose_for` does. This is the regression for the
    value/field pairing -- `propose.py` reads the decision word out of
    `route.value`, so a routed "status"/"confirmed" pair that never made
    it through validation would have come out with no status at all."""
    from app.engine import conversation as conv

    statement = _scope(db, project, dana)
    screen = {"name": "confirm", "sheet": "", "selection": "", "filter": None,
             "records": [f"scope:{statement.id}"]}

    def fake(message, screen_line):
        return {"intent": "decide_scope", "target_form": "record", "tag": "",
                "record_key": f"scope:{statement.id}", "field": "status", "value": "confirmed"}

    monkeypatch.setattr(conv.llm, "available", lambda: True)
    monkeypatch.setattr(conv.llm, "route_message", fake)
    route = conv.route_message("site lighting is by others, that's right", screen=screen)
    out = propose.build(db, project=project, route=route, screen=_screen(name="confirm"),
                        message="site lighting is by others, that's right")
    assert out["kind"] == "scope" and out["status"] == "confirmed"


def test_a_record_key_the_screen_does_not_offer_proposes_nothing(db, project, dana):
    statement = _scope(db, project, dana)
    # Right key, wrong screen: the blueprint shows no scope statements.
    assert propose.build(db, project=project,
                         route=_route("decide_scope", form="record", record_key=f"scope:{statement.id}",
                                      field="status", value="confirmed"),
                         screen=_screen(name="takeoff"), message="confirm that") is None
    # Invented key, right screen.
    assert propose.build(db, project=project,
                         route=_route("decide_scope", form="record", record_key=f"scope:{uuid.uuid4()}",
                                      field="status", value="confirmed"),
                         screen=_screen(name="confirm"), message="confirm that") is None


def test_over_the_cap_refuses_with_copy_rather_than_proposing(db, project, monkeypatch):
    sheet = _sheet(db, project)
    for n in range(3):
        _item(db, project, sheet, source_tag=f"T{n}")
    monkeypatch.setattr(propose.targets, "MAX_TARGETS", 2)
    out = propose.build(db, project=project, route=_route("reclassify", form="view"),
                        screen=_screen(sheet_id=sheet.id), message="these are all type F")
    assert out["kind"] == "refused"
    assert "3 items" in out["summary"] and "Narrow it down" in out["summary"]


def test_no_proposal_names_internals(db, project, monkeypatch):
    sheet = _sheet(db, project)
    a = _item(db, project, sheet)
    monkeypatch.setattr(propose.resolve_service, "resolve_for_item",
                        lambda db_, item, text, *, cluster=True: _resolved([a]))
    built = [propose.build(db, project=project, route=_route("reclassify"),
                           screen=_screen(sheet_id=sheet.id, item_id=a.id), message="type F"),
             propose.build(db, project=project, route=_route("set_context", form="none", field="text",
                                                             value="Ceiling is 14 feet."),
                           screen=_screen(), message="Ceiling is 14 feet.")]
    blob = json.dumps([b for b in built if b]).lower()
    assert not any(w in blob for w in ("confidence", "model", "llm", "run_id", "attempt", "opus", "prompt"))
    assert "!" not in blob and "please" not in blob


def test_record_keys_lists_only_what_the_screen_offers(db, project, dana):
    statement = _scope(db, project, dana)
    assert f"scope:{statement.id}" in propose.record_keys(db, project, _screen(name="confirm"))
    assert propose.record_keys(db, project, _screen(name="takeoff")) == []


# --- staleness: what stops a card applying to something that moved ---


def test_an_item_proposal_goes_stale_when_a_target_moves_or_vanishes(db, project, monkeypatch):
    sheet = _sheet(db, project)
    a, b = _item(db, project, sheet), _item(db, project, sheet)
    monkeypatch.setattr(propose.resolve_service, "resolve_for_item",
                        lambda db_, item, text, *, cluster=True: _resolved([a, b]))
    built = propose.build(db, project=project, route=_route("reclassify"),
                          screen=_screen(sheet_id=sheet.id, item_id=a.id), message="type F")
    assert propose.is_stale(db, project=project, proposal=built) is False
    b.version += 1
    db.flush()
    assert propose.is_stale(db, project=project, proposal=built) is True


def test_a_scope_proposal_is_stale_once_the_statement_already_says_so(db, project, dana):
    statement = _scope(db, project, dana)
    built = propose.build(db, project=project,
                          route=_route("decide_scope", form="record", record_key=f"scope:{statement.id}",
                                       field="status", value="confirmed"),
                          screen=_screen(name="confirm"), message="that's right")
    assert propose.is_stale(db, project=project, proposal=built) is False
    statement.status = "confirmed"
    db.flush()
    assert propose.is_stale(db, project=project, proposal=built) is True


def _spec_doc(db, project, dana):
    d = Document(project_id=project.id, filename="Spec.pdf", doc_type="Specifications", content_type="application/pdf",
                 size_bytes=1, sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id, status="processed",
                 context_text="SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES\n")
    db.add(d); db.flush(); return d


def test_a_plan_line_proposal_goes_stale_once_that_line_already_carries_the_proposed_status(db, project, dana):
    _spec_doc(db, project, dana)
    plan = plan_service.build_plan(db, project)
    line = plan.specs[0]
    key = f"plan:{line.key}"
    out = propose.build(db, project=project,
                        route=_route("decide_plan", form="record", record_key=key, field="status", value="confirmed"),
                        screen=_screen(name="plan"), message="that's right")
    assert out["kind"] == "plan_line" and out["status"] == "confirmed"
    assert propose.is_stale(db, project=project, proposal=out) is False
    plan_service.decide(db, actor=dana, project=project, key=line.key, status="confirmed")
    assert propose.is_stale(db, project=project, proposal=out) is True


def test_a_plan_answer_proposal_goes_stale_once_the_question_is_answered(db, project, dana):
    sheet = _sheet(db, project)  # a "plan" sheet with no scale -- a no_scale question
    plan = plan_service.build_plan(db, project)
    question = next(q for q in plan.questions if q.key.startswith("question:no_scale:"))
    key = f"plan:{question.key}"
    out = propose.build(db, project=project,
                        route=_route("decide_plan", form="record", record_key=key, field="text",
                                     value="It's 1/8 inch = 1 foot."),
                        screen=_screen(name="plan"), message="it's 1/8 inch = 1 foot")
    assert out["kind"] == "plan_answer"
    assert propose.is_stale(db, project=project, proposal=out) is False
    plan_service.answer(db, actor=dana, project=project, key=question.key, body="It's 1/8 inch = 1 foot.")
    assert propose.is_stale(db, project=project, proposal=out) is True


def test_a_note_is_never_stale_and_a_refusal_always_is(db, project):
    note = propose.build(db, project=project, route=_route("set_context", form="none", field="text", value="14 feet"),
                         screen=_screen(), message="14 feet")
    assert propose.is_stale(db, project=project, proposal=note) is False
    assert propose.is_stale(db, project=project, proposal={"kind": "refused", "summary": "x"}) is True


# --- the closed set is enforced, not just declared ---


def test_build_refuses_to_return_a_kind_outside_the_closed_set(db, project, monkeypatch):
    """PROPOSAL_KINDS is the arm list. A builder that ever returned
    something outside it would ship an unregistered proposal kind to the
    wire silently -- build asserts instead, so that is a hard failure
    here rather than a mystery in the panel."""
    monkeypatch.setattr(propose, "_note_from", lambda value, message: {"kind": "bogus", "summary": "x"})
    with pytest.raises(ValueError):
        propose.build(db, project=project,
                      route=_route("set_context", form="none", field="text", value="14 feet"),
                      screen=_screen(), message="14 feet")
