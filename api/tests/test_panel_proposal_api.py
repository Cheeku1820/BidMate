"""The proposal on the wire: one event after the answer, the column it
is stored in, and the bookkeeping route that records what became of it.
Nothing here writes a takeoff record -- the card's Apply calls the
record's own endpoint, which these tests do not go through."""

import contextlib
import json
import uuid

import pytest
from sqlalchemy import text

from app.assistant import service
from app.assistant.models import ConversationMessage
from app.takeoff.models import Document, Item, ReviewStatus, Sheet


@pytest.fixture(autouse=True)
def _real_session(monkeypatch, db):
    """`service.answer_events`/`propose_for` open their own session through
    `answer_session` -- by default a fresh `SessionLocal()` against the
    shared dev database (DATABASE_URL), not the per-worktree database this
    test's `project` was written to (TEST_DATABASE_URL). Same fix
    `test_assistant_router.py`'s `model` fixture already applies, needed
    here too since some tests below call `service.answer_events` directly
    rather than through the router's request-scoped session."""
    monkeypatch.setattr(service, "answer_session", lambda: contextlib.nullcontext(db))


def _events(body) -> list[tuple[str, dict]]:
    out = []
    for block in "".join(body).split("\n\n"):
        if not block.strip():
            continue
        name = block.split("event: ", 1)[1].split("\n", 1)[0]
        data = json.loads(block.split("data: ", 1)[1])
        out.append((name, data))
    return out


@pytest.fixture
def sheet_and_item(db, project):
    sheet = Sheet(project_id=project.id, number="E2.1", title="Power plan", discipline="Electrical",
                  revision="", scale="", scale_options=[], plan="")
    db.add(sheet); db.flush()
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="unknown", name="Unclassified symbol",
                system="Unknown", category="Unclassified", quantity=6, unit="EA",
                status=ReviewStatus.ATTENTION, source_tag="F")
    db.add(item); db.flush()
    return sheet, item


def test_the_proposal_event_arrives_between_the_deltas_and_done(client, db, project, dana, signed_in_user,
                                                                sheet_and_item, monkeypatch):
    sheet, item = sheet_and_item
    monkeypatch.setattr(service.llm, "stream", lambda system, messages: iter(["Six items ", "read as type F."]))
    monkeypatch.setattr(service, "propose_for",
                        lambda **kw: {"kind": "note", "summary": "Add a note to this project: Ceiling is 14 feet",
                                      "title": "Ceiling is 14 feet", "body": "Ceiling is 14 feet.",
                                      "category": "existing_condition", "usage": "context",
                                      "targets_preview": [], "more_count": 0})
    body = service.answer_events(project_id=project.id, actor_id=dana.id, bundle_text="ctx",
                                 messages=[{"role": "user", "content": "ceiling is 14 feet"}],
                                 message_text="ceiling is 14 feet", screen={"name": "takeoff"})
    names = [name for name, _ in _events(body)]
    assert names == ["delta", "delta", "proposal", "done"]


def test_no_event_when_nothing_is_proposable(client, db, project, dana, signed_in_user, monkeypatch):
    monkeypatch.setattr(service.llm, "stream", lambda system, messages: iter(["Fourteen sheets."]))
    monkeypatch.setattr(service, "propose_for", lambda **kw: None)
    body = service.answer_events(project_id=project.id, actor_id=dana.id, bundle_text="ctx",
                                 messages=[{"role": "user", "content": "how many sheets?"}],
                                 message_text="how many sheets?", screen={"name": "takeoff"})
    assert [name for name, _ in _events(body)] == ["delta", "done"]


def test_the_proposal_is_stored_offered_and_comes_back_on_the_thread(client, db, project, dana, signed_in_user,
                                                                     monkeypatch):
    monkeypatch.setattr(service.llm, "stream", lambda system, messages: iter(["Noted."]))
    monkeypatch.setattr(service, "propose_for",
                        lambda **kw: {"kind": "note", "summary": "Add a note to this project: Ceiling",
                                      "title": "Ceiling", "body": "Ceiling is 14 feet.",
                                      "category": "existing_condition", "usage": "context",
                                      "targets_preview": [], "more_count": 0})
    list(service.answer_events(project_id=project.id, actor_id=dana.id, bundle_text="ctx",
                               messages=[{"role": "user", "content": "ceiling is 14 feet"}],
                               message_text="ceiling is 14 feet", screen={"name": "takeoff"}))
    thread = client.get(f"/api/projects/{project.id}/conversation").json()["messages"]
    answer = [m for m in thread if m["role"] == "answer"][-1]
    assert answer["proposal"]["kind"] == "note" and answer["proposal_status"] == "offered"


def test_the_status_route_records_applied_and_dismissed(client, db, project, dana, signed_in_user):
    row = ConversationMessage(project_id=project.id, role="answer", text="…", created_by=dana.id,
                              proposal={"kind": "note", "summary": "x"}, proposal_status="offered")
    db.add(row); db.flush()
    url = f"/api/projects/{project.id}/conversation/messages/{row.id}/proposal"
    assert client.patch(url, json={"status": "applied"}).json()["proposal_status"] == "applied"
    # Already settled: refused, with the current status named.
    second = client.patch(url, json={"status": "dismissed"})
    assert second.status_code == 409 and second.json()["detail"]["code"] == "proposal_settled"
    other = ConversationMessage(project_id=project.id, role="answer", text="…", created_by=dana.id,
                                proposal={"kind": "note", "summary": "y"}, proposal_status="offered")
    db.add(other); db.flush()
    assert client.patch(f"/api/projects/{project.id}/conversation/messages/{other.id}/proposal",
                        json={"status": "dismissed"}).json()["proposal_status"] == "dismissed"


def test_a_message_with_no_proposal_and_a_bad_status_are_refused(client, db, project, dana, signed_in_user):
    plain = ConversationMessage(project_id=project.id, role="answer", text="…", created_by=dana.id)
    db.add(plain); db.flush()
    assert client.patch(f"/api/projects/{project.id}/conversation/messages/{plain.id}/proposal",
                        json={"status": "applied"}).status_code == 404
    assert client.patch(f"/api/projects/{project.id}/conversation/messages/{uuid.uuid4()}/proposal",
                        json={"status": "applied"}).status_code == 404
    with_proposal = ConversationMessage(project_id=project.id, role="answer", text="…", created_by=dana.id,
                                        proposal={"kind": "note"}, proposal_status="offered")
    db.add(with_proposal); db.flush()
    assert client.patch(f"/api/projects/{project.id}/conversation/messages/{with_proposal.id}/proposal",
                        json={"status": "offered"}).status_code == 422


def test_the_status_route_writes_no_action(client, db, project, dana, signed_in_user):
    from sqlalchemy import select
    from app.takeoff.models import Action
    row = ConversationMessage(project_id=project.id, role="answer", text="…", created_by=dana.id,
                              proposal={"kind": "note", "summary": "x"}, proposal_status="offered")
    db.add(row); db.flush()
    client.patch(f"/api/projects/{project.id}/conversation/messages/{row.id}/proposal", json={"status": "applied"})
    assert db.scalars(select(Action).where(Action.project_id == project.id)).all() == []


def test_a_stale_stored_proposal_says_so_on_the_thread(client, db, project, dana, signed_in_user, sheet_and_item):
    sheet, item = sheet_and_item
    row = ConversationMessage(
        project_id=project.id, role="answer", text="…", created_by=dana.id, proposal_status="offered",
        proposal={"kind": "item", "summary": "Name one item.", "note": "Approving stays with you.",
                  "count": 1, "sheet_number": "E2.1", "item_id": str(item.id), "approve": False,
                  "targets_preview": [], "more_count": 0,
                  "proposal": {"target_item_ids": [str(item.id)], "versions": {str(item.id): item.version + 5}}})
    db.add(row); db.flush()
    thread = client.get(f"/api/projects/{project.id}/conversation").json()["messages"]
    answer = [m for m in thread if m["role"] == "answer"][-1]
    assert answer["proposal_status"] == "stale"


def test_a_get_never_persists_the_stage_advance_a_stale_check_can_reach(client, db, project, dana, signed_in_user):
    """A plan_line proposal's staleness goes through plan_service.build_plan
    (propose._plan_stale), which stages a project-stage advance via
    db.execute(update(...)) + db.flush() whenever a processed drawing set
    is on the project -- see GET /plan, which commits right after for
    exactly that reason. Reading the conversation thread must never move
    the stage: asserted with a raw query on the same session, since a
    flushed-but-not-committed update is otherwise indistinguishable from
    a committed one within this transaction."""
    db.execute(text("update projects set stage = 'documents' where id = :id"), {"id": str(project.id)})
    db.flush()
    doc = Document(project_id=project.id, filename="E-set.pdf", doc_type="Drawings", content_type="application/pdf",
                   size_bytes=1, sha256="a" * 64, storage_key="k", uploaded_by=dana.id, status="processed")
    db.add(doc); db.flush()
    row = ConversationMessage(project_id=project.id, role="answer", text="…", created_by=dana.id,
                              proposal_status="offered",
                              proposal={"kind": "plan_line", "key": "spec:none:0", "summary": "x",
                                        "current_text": "x", "targets_preview": [], "more_count": 0})
    db.add(row); db.flush()
    # Committed, not just flushed: `client` reuses this same session across
    # the request, so only a real commit boundary lets the assertion below
    # tell "the route's own rollback discarded its own flush" apart from
    # "the route's rollback discarded everything this test staged."
    db.commit()
    assert client.get(f"/api/projects/{project.id}/conversation").status_code == 200
    stage = db.execute(text("select stage from projects where id = :id"), {"id": str(project.id)}).scalar_one()
    assert stage == "documents"


def test_a_proposal_kind_outside_the_closed_set_reads_as_stale(client, db, project, dana, signed_in_user):
    """PROPOSAL_KINDS is the arm list `propose.build` is now asserted
    against; a row stored before that assertion existed, or one written
    directly, must still degrade safely rather than offer an Apply the
    thread has no builder for."""
    row = ConversationMessage(project_id=project.id, role="answer", text="…", created_by=dana.id,
                              proposal_status="offered", proposal={"kind": "not_a_real_kind", "summary": "x"})
    db.add(row); db.flush()
    thread = client.get(f"/api/projects/{project.id}/conversation").json()["messages"]
    answer = next(m for m in thread if m["id"] == str(row.id))
    assert answer["proposal_status"] == "stale"


def test_a_malformed_stored_proposal_degrades_only_its_own_card(client, db, project, dana, signed_in_user):
    bad = ConversationMessage(project_id=project.id, role="answer", text="…", created_by=dana.id,
                              proposal_status="offered",
                              proposal={"kind": "item", "summary": "x",
                                        "proposal": {"target_item_ids": ["not-a-uuid"],
                                                     "versions": {"not-a-uuid": 1}}})
    db.add(bad); db.flush()
    fine = ConversationMessage(project_id=project.id, role="answer", text="fine", created_by=dana.id)
    db.add(fine); db.flush()
    res = client.get(f"/api/projects/{project.id}/conversation")
    assert res.status_code == 200
    thread = res.json()["messages"]
    bad_out = next(m for m in thread if m["id"] == str(bad.id))
    assert bad_out["proposal_status"] == "offered"
    assert any(m["id"] == str(fine.id) for m in thread)
