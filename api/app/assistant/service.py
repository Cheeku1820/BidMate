# api/app/assistant/service.py
"""The thread and the answer stream.

The route handler does every read and the estimator-turn write inside
the request -- FastAPI closes a Depends(get_db) session before a
StreamingResponse body runs -- and hands answer_events() plain values.
The generator opens its own session through `answer_session` only to
store the answer, at the end. Tests replace `answer_session` with one
that yields their session.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections.abc import Iterator

from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session as DbSession

from app.assistant import llm
from app.assistant.context import build
from app.assistant.models import ConversationMessage
from app.assistant.prompt import SYSTEM_PROMPT, render
from app.assistant.schemas import ScreenIn
from app.db import SessionLocal
from app.identity.models import User
from app.observability import request_id_var
from app.takeoff.models import Project

logger = logging.getLogger(__name__)

HISTORY_TURNS = 20
THREAD_CAP = 200

BUSY = ("busy", "Busy right now — ask again in a moment")
INTERRUPTED = ("interrupted", "Answer interrupted — ask again")
# A key that is present but rejected (401/403) is the same problem as
# no key: a setup one, not one a retry fixes. Same words as the 503.
NOT_CONFIGURED = ("not_configured", "The conversation panel isn't set up on this server")


@contextlib.contextmanager
def _default_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


answer_session = _default_session


def list_messages(db: DbSession, project_id: uuid.UUID) -> list[ConversationMessage]:
    """The last THREAD_CAP turns, oldest first.

    Ordered ascending with an offset rather than descending-then-reversed:
    rows inserted in the same transaction can share created_at (Postgres'
    now() is fixed for the transaction), and the id is a random uuid4, so
    a desc/reverse pair over ties does not reproduce insertion order --
    an ascending scan with LIMIT/OFFSET reads the same ties in the table's
    physical (insertion) order instead."""
    total = db.scalar(
        select(func.count()).select_from(ConversationMessage).where(ConversationMessage.project_id == project_id)
    )
    offset = max(total - THREAD_CAP, 0)
    return list(db.scalars(
        select(ConversationMessage).where(ConversationMessage.project_id == project_id)
        .order_by(ConversationMessage.created_at, sql_text("ctid"))
        .offset(offset).limit(THREAD_CAP)
    ))


def store_estimator_turn(db: DbSession, *, actor: User, project: Project, text: str, screen: ScreenIn) -> ConversationMessage:
    row = ConversationMessage(project_id=project.id, role="estimator", text=text,
                              screen=screen.model_dump(mode="json"), created_by=actor.id)
    db.add(row)
    db.flush()
    return row


def history_for_model(db: DbSession, project_id: uuid.UUID) -> list[dict]:
    """The last HISTORY_TURNS turns of prior history as the model's
    user/assistant pairs, plus the newest estimator turn on top of them
    (it was stored before this is called) -- HISTORY_TURNS + 1 messages
    at most. Product words stay on our side of the boundary; the SDK's
    roles are the SDK's.

    The window can start mid-turn: a busy/interrupted answer stores its
    estimator turn without a matching answer, so the thread is not
    strictly estimator/answer-alternating, and a fixed-size tail can
    begin with a leftover answer row. The Messages API 400s on a
    non-user first message, so leading rows are dropped until the tail
    starts with an estimator turn -- never empty, since the turn just
    stored by `prepare()` is always last."""
    turns = list_messages(db, project_id)[-(HISTORY_TURNS + 1):]
    while turns and turns[0].role != "estimator":
        turns.pop(0)
    return [{"role": "user" if t.role == "estimator" else "assistant", "content": t.text} for t in turns]


def prepare(db: DbSession, *, actor: User, project: Project, text: str, screen: ScreenIn) -> tuple[str, list[dict]]:
    """Everything the stream needs, computed while the request's session
    is open: the rendered bundle and the turns."""
    bundle_text = render(build(db, actor, project, screen))
    store_estimator_turn(db, actor=actor, project=project, text=text, screen=screen)
    db.commit()
    return bundle_text, history_for_model(db, project.id)


def _event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


def _failed(outcome: tuple[str, str]) -> str:
    """Log the exception being handled, with the request id so the log
    line and the panel's X-Request-Id meet, and render the error event.
    The exception's text never reaches the wire: the panel shows only
    the recovery copy."""
    code, message = outcome
    logger.warning("conversation answer failed (%s) request_id=%s", code, request_id_var.get(), exc_info=True)
    return _event("error", {"code": code, "message": message})


def answer_events(*, project_id: uuid.UUID, actor_id: uuid.UUID, bundle_text: str, messages: list[dict]) -> Iterator[str]:
    """The SSE body. Yields delta events as text arrives, then done with
    the stored answer's id; on failure an error event and nothing stored."""
    import anthropic

    system_blocks = [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": bundle_text, "cache_control": {"type": "ephemeral"}},
    ]
    chunks: list[str] = []
    try:
        for chunk in llm.stream(system_blocks, messages):
            chunks.append(chunk)
            yield _event("delta", {"text": chunk})
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        yield _failed(NOT_CONFIGURED)
        return
    except anthropic.RateLimitError:
        yield _failed(BUSY)
        return
    except anthropic.APIStatusError as exc:
        yield _failed(BUSY if exc.status_code == 529 else INTERRUPTED)
        return
    except Exception:  # noqa: BLE001 -- connection drops and anything else: the panel says "ask again"
        yield _failed(INTERRUPTED)
        return

    # The deltas are already on the wire; a failed store must still end
    # the body with an event the panel can render, not a dropped
    # connection. Nothing is stored, so the thread reloads without it.
    try:
        with answer_session() as db:
            row = ConversationMessage(project_id=project_id, role="answer", text="".join(chunks), created_by=actor_id)
            db.add(row)
            db.commit()
            answer_id = str(row.id)
    except Exception:  # noqa: BLE001
        yield _failed(INTERRUPTED)
        return
    yield _event("done", {"id": answer_id})
