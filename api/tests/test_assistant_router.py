"""app/assistant/router.py and service.py -- the thread and the answer
stream. The model is replaced by a fake everywhere below: these tests
prove what is stored, in what order, and what the wire carries, not
what Claude says."""
import os

from app.assistant import llm


def test_availability_follows_the_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.available() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm.available() is True
    assert llm.MODEL == "claude-opus-5"


import contextlib
import json

import pytest
from sqlalchemy import select

from app.assistant import service
from app.assistant.models import ConversationMessage


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def model(monkeypatch, db):
    """A fake model: records what it was asked, answers in two chunks,
    and stores the answer through the test session rather than a fresh
    SessionLocal() pointed at the dev database."""
    calls = []

    def fake_stream(system_blocks, messages):
        calls.append({"system": system_blocks, "messages": messages})
        yield "Nothing is blocking export. "
        yield "One item is Needs attention on E2.1."

    monkeypatch.setattr(service.llm, "stream", fake_stream)
    monkeypatch.setattr(service.llm, "available", lambda: True)
    monkeypatch.setattr(service, "answer_session", lambda: contextlib.nullcontext(db))
    return calls


def _post(client, project, text="What's blocking export?", screen=None):
    return client.post(f"/api/projects/{project.id}/conversation/messages",
                       json={"text": text, "screen": screen or {"name": "export"}})


def test_the_stream_carries_deltas_then_done_and_both_turns_are_stored(client, signed_in_user, project, model):
    res = _post(client, project)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    events = _events(res.text)
    assert events[0] == ("delta", {"text": "Nothing is blocking export. "})
    assert events[1] == ("delta", {"text": "One item is Needs attention on E2.1."})
    assert events[2][0] == "done"

    thread = client.get(f"/api/projects/{project.id}/conversation").json()["messages"]
    assert [m["role"] for m in thread] == ["estimator", "answer"]
    assert thread[0]["text"] == "What's blocking export?"
    assert thread[0]["screen"] == {"name": "export", "sheet_id": None, "item_id": None, "view": None}
    assert thread[1]["text"] == "Nothing is blocking export. One item is Needs attention on E2.1."
    assert thread[1]["screen"] is None
    assert thread[1]["id"] == events[2][1]["id"]


def test_the_model_sees_the_frozen_prompt_then_the_bundle_then_the_turns(client, signed_in_user, project, model):
    _post(client, project, text="First question")
    _post(client, project, text="Second question")
    call = model[1]
    assert [b["cache_control"] for b in call["system"]] == [{"type": "ephemeral"}, {"type": "ephemeral"}]
    assert call["system"][0]["text"].startswith("You are answering questions for an electrical estimator")
    assert "<project>" in call["system"][1]["text"]
    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]
    assert call["messages"][-1]["content"] == "Second question"


def test_history_is_capped_at_twenty_turns(client, signed_in_user, project, model):
    for n in range(12):
        _post(client, project, text=f"q{n}")
    assert len(model[-1]["messages"]) == service.HISTORY_TURNS + 1


def test_a_non_alternating_thread_still_starts_the_model_on_a_user_turn(client, signed_in_user, project, dana, db, model):
    """A busy/interrupted answer stores its estimator turn without a
    matching answer (test_an_error_mid_stream_stores_no_answer), so a
    real thread is not strictly estimator/answer-alternating. Seeds a
    thread shaped e a e e a e a ... (21 rows -- one more than the
    naive tail's drop point needs, with the doubled e a failed turn
    early on) so that the fixed-size HISTORY_TURNS + 1 window, taken
    naively from the end, would start on a leftover "answer" row once
    the new post's own estimator turn pushes the thread past the cap.
    The model must never see that row first: the Messages API 400s on
    an assistant-first message list."""
    roles = ["estimator", "answer", "estimator", "estimator"]
    role = "answer"
    for _ in range(17):
        roles.append(role)
        role = "estimator" if role == "answer" else "answer"
    assert len(roles) == 21
    for n, role in enumerate(roles):
        db.add(ConversationMessage(project_id=project.id, role=role, text=f"m{n}", created_by=dana.id))
    db.flush()

    _post(client, project, text="Latest question")

    messages = model[-1]["messages"]
    assert len(messages) <= service.HISTORY_TURNS + 1
    assert messages[0]["role"] == "user"


def test_an_error_mid_stream_stores_no_answer(client, signed_in_user, project, model, monkeypatch, db):
    import anthropic
    import httpx2

    def failing(system_blocks, messages):
        yield "Partial "
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "http://x"))

    monkeypatch.setattr(service.llm, "stream", failing)
    res = _post(client, project)
    events = _events(res.text)
    assert events[0] == ("delta", {"text": "Partial "})
    assert events[1] == ("error", {"code": "interrupted", "message": "Answer interrupted — ask again"})
    roles = [m.role for m in db.scalars(select(ConversationMessage).where(ConversationMessage.project_id == project.id))]
    assert roles == ["estimator"]


def test_rate_limit_is_busy(client, signed_in_user, project, model, monkeypatch):
    import anthropic
    import httpx2

    def limited(system_blocks, messages):
        raise anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=httpx2.Request("POST", "http://x")),
                                       body=None)
        yield  # noqa: unreachable -- makes this a generator

    monkeypatch.setattr(service.llm, "stream", limited)
    events = _events(_post(client, project).text)
    assert events == [("error", {"code": "busy", "message": "Busy right now — ask again in a moment"})]


def test_without_a_key_the_route_says_so_before_streaming(client, signed_in_user, project, monkeypatch):
    monkeypatch.setattr(service.llm, "available", lambda: False)
    res = _post(client, project)
    assert res.status_code == 503
    assert res.json()["detail"] == {"code": "not_configured",
                                    "message": "The conversation panel isn't set up on this server"}


def test_screen_outside_the_set_is_422(client, signed_in_user, project, model):
    assert _post(client, project, screen={"name": "dashboard"}).status_code == 422


def test_cross_org_project_is_the_standard_404(client, signed_in_user, db, model):
    from app.identity.models import Org
    from app.takeoff.models import Project

    other = Org(name="Rival Electric")
    db.add(other)
    db.flush()
    theirs = Project(org_id=other.id, name="Their job", revision_set_label="")
    db.add(theirs)
    db.flush()
    assert client.get(f"/api/projects/{theirs.id}/conversation").status_code == 404
    assert _post(client, theirs).status_code == 404


def test_get_is_oldest_first_and_capped(client, signed_in_user, project, dana, db):
    for n in range(service.THREAD_CAP + 3):
        db.add(ConversationMessage(project_id=project.id, role="estimator", text=f"m{n}", created_by=dana.id))
    db.flush()
    msgs = client.get(f"/api/projects/{project.id}/conversation").json()["messages"]
    assert len(msgs) == service.THREAD_CAP
    assert msgs[0]["text"] == "m3" and msgs[-1]["text"] == f"m{service.THREAD_CAP + 2}"
