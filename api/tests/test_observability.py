"""Request-id middleware and structured logging -- task-14-brief.md.

The plan's sketch (docs/superpowers/plans/2026-08-07-backend-spine.md,
"Task 14") has five corrections applied here, per the brief:

1. `JsonFormatter` must not discard `exc_info` -- the whole value of
   `logging.exception("unhandled error")` is the traceback it carries,
   and the sketch's formatter only emitted level/message/logger/
   request_id. A timestamp is added too; a structured log with no time on
   it is close to useless.
2. A client-supplied `X-Request-Id` is never trusted into a log line or
   an outbound header -- the id is always generated server-side. There is
   no trusted upstream proxy in front of this API yet, so accepting an
   inbound value would let an attacker choose what appears, unvalidated,
   in every log line for that request (a JSON log-forging vector), and
   would let two unrelated requests share one id if the header were
   replayed.
3. The sketch's second test registers `/api/boom` directly on
   `main.app`, which would permanently add a route to the shared app for
   the rest of the test session -- exactly what
   `test_every_project_scoped_route_is_covered_by_the_tenancy_table`
   (test_tenancy.py, Task 13) enumerates and asserts against. Tests here
   build a throwaway `FastAPI()` instance instead and never touch
   `main.app`'s routes.
4. `configure_logging()` must not clobber pytest's own log-capture setup
   -- it no-ops when running under pytest (see its docstring in
   app/observability.py) rather than replacing `root.handlers` wholesale
   during test collection.
5. The request-id header has to survive every response shape the app
   produces: a plain 200, a 304 (`/snapshot`'s conditional GET), a 204
   (`PUT /presence`), a `DomainError`/`CrossOrgActionError` JSON
   response, and an unhandled-exception 500 -- and that last one has to
   keep carrying `no_shared_caching`'s `Cache-Control`/`Vary` headers
   too, which only happens if `RequestIdMiddleware` is registered so it
   sits *inside* `no_shared_caching` (added to `main.app` first, per
   Starlette's last-added-is-outermost ordering for user middleware) --
   otherwise a synthesized 500 would skip `no_shared_caching`'s
   post-processing entirely.
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as main_app
from app.observability import JsonFormatter, RequestIdMiddleware, configure_logging, request_id_var


def _sign_in(client, email="dana@example.com", password="correct-horse"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _throwaway_app() -> FastAPI:
    """A standalone app carrying the same two middlewares as `main.app`,
    in the same order, so the ordering guarantee (correction 5) can be
    tested without ever mutating the shared `main.app` (correction 3).
    """
    throwaway = FastAPI()
    throwaway.add_middleware(RequestIdMiddleware)

    @throwaway.middleware("http")
    async def no_shared_caching(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Cookie"
        return response

    @throwaway.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    @throwaway.get("/fine")
    def fine():
        return {"ok": True}

    return throwaway


# --- The plan's two, corrected ---


def test_every_response_carries_a_request_id(client):
    response = client.get("/api/health")

    assert response.headers["x-request-id"]


def test_an_unexpected_error_reports_an_id_the_user_can_quote():
    with TestClient(_throwaway_app()) as c:
        response = c.get("/boom")

    assert response.status_code == 500
    assert response.json()["detail"]["request_id"] == response.headers["x-request-id"]
    assert "kaboom" not in response.text
    assert response.json()["detail"]["message"]
    # Sentence case, no exclamation marks, names a recovery action --
    # CLAUDE.md's copy rules -- and never "Something went wrong" alone.
    message = response.json()["detail"]["message"]
    assert message != "Something went wrong"
    assert "try again" in message.lower()


# --- Correction 5: the header, and no_shared_caching's headers, survive
# every response shape ---


def test_a_synthesized_500_still_carries_the_no_store_cache_headers():
    """The failure this guards against: if RequestIdMiddleware were
    registered *outside* no_shared_caching, an unhandled exception caught
    by RequestIdMiddleware would produce a response that never passes
    back through no_shared_caching's post-processing, and a bid-relevant
    error page would ship without Cache-Control: private, no-store.
    """
    with TestClient(_throwaway_app()) as c:
        response = c.get("/boom")

    assert response.status_code == 500
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def test_an_ordinary_response_carries_both_headers_too():
    with TestClient(_throwaway_app()) as c:
        response = c.get("/fine")

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "private, no-store"


def test_main_app_registers_request_id_middleware_inside_the_cache_middleware():
    """A structural check on the real app, so the ordering guarantee
    doesn't rely only on a parallel throwaway app matching it by
    coincidence. `add_middleware` prepends to `Starlette.user_middleware`,
    so the entry added *second* (no_shared_caching, registered after
    RequestIdMiddleware in main.py) sits at a lower index -- lower index
    is outermost once Starlette builds the ASGI stack.
    """
    classes = []
    for mw in main_app.user_middleware:
        dispatch = mw.kwargs.get("dispatch")
        classes.append(dispatch.__name__ if dispatch is not None else mw.cls.__name__)

    assert "no_shared_caching" in classes
    assert "RequestIdMiddleware" in classes
    assert classes.index("no_shared_caching") < classes.index("RequestIdMiddleware"), (
        "no_shared_caching must be outermost (added after RequestIdMiddleware) so a "
        "synthesized 500 still gets its Cache-Control/Vary headers"
    )


def test_a_304_snapshot_response_still_carries_a_request_id(client, dana, project, sheet, item):
    _sign_in(client)
    etag = client.get(f"/api/projects/{project.id}/snapshot").headers["etag"]

    response = client.get(f"/api/projects/{project.id}/snapshot", headers={"If-None-Match": etag})

    assert response.status_code == 304
    assert response.headers["x-request-id"]


def test_a_204_presence_response_still_carries_a_request_id(client, dana, project):
    _sign_in(client)

    response = client.put("/api/presence", json={"project_id": str(project.id)})

    assert response.status_code == 204
    assert response.headers["x-request-id"]


def test_a_domain_error_response_still_carries_a_request_id(client, dana, project, sheet, item):
    _sign_in(client)
    from app.takeoff.models import ReviewStatus

    item.status = ReviewStatus.MISSING

    response = client.post(f"/api/items/{item.id}/approve", headers={"If-Match": str(item.version)})

    assert response.status_code == 409
    assert response.headers["x-request-id"]


def test_a_cross_org_action_error_response_still_carries_a_request_id(client, dana, project, sheet, item, db):
    from app.auth.passwords import hash_password
    from app.identity.models import Org, User

    rival_org = Org(name="Rival Electric")
    db.add(rival_org)
    db.flush()
    rival = User(org_id=rival_org.id, email="rival@example.com",
                 password_hash=hash_password("hunter2"), name="Rival Estimator", color="#a8412c")
    db.add(rival)
    db.flush()
    _sign_in(client, "rival@example.com", "hunter2")

    response = client.get(f"/api/projects/{project.id}/snapshot")

    assert response.status_code == 404
    assert response.headers["x-request-id"]


# --- Two independent ids for two independent requests ---


def test_two_requests_never_share_a_generated_id(client):
    first = client.get("/api/health").headers["x-request-id"]
    second = client.get("/api/health").headers["x-request-id"]

    assert first != second


def test_a_client_supplied_request_id_header_is_ignored_not_echoed(client):
    """Correction 2: an inbound X-Request-Id must never be trusted
    straight into a response header or a log line -- it is always
    generated server-side, so a value chosen by the caller cannot poison
    another request's log correlation or carry log-forging characters
    into a JSON-formatted log line.
    """
    response = client.get("/api/health", headers={"X-Request-Id": "attacker-supplied\nvalue"})

    assert response.headers["x-request-id"] != "attacker-supplied\nvalue"
    assert "\n" not in response.headers["x-request-id"]


# --- JsonFormatter: corrections 1 (exc_info, timestamp) ---


def _record(**overrides):
    defaults = dict(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    defaults.update(overrides)
    return logging.LogRecord(**defaults)


def test_json_formatter_emits_level_message_logger_request_id_and_timestamp():
    import json

    token = request_id_var.set("req-abc123")
    try:
        payload = json.loads(JsonFormatter().format(_record()))
    finally:
        request_id_var.reset(token)

    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert payload["logger"] == "app.test"
    assert payload["request_id"] == "req-abc123"
    assert payload["timestamp"]


def test_json_formatter_includes_the_traceback_when_present():
    """The sketch's formatter dropped `exc_info` entirely, so
    `logging.exception("unhandled error")` -- the 500 path's only call --
    logged the literal string "unhandled error" and discarded the
    traceback that is the whole point of calling .exception() instead of
    .error(). This is the regression test for that.
    """
    import json

    try:
        raise ValueError("boom")
    except ValueError:
        record = _record(msg="unhandled error", exc_info=True)
        import sys
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))

    assert "boom" in payload["exc_info"]
    assert "ValueError" in payload["exc_info"]


def test_json_formatter_omits_exc_info_key_when_there_is_no_exception():
    import json

    payload = json.loads(JsonFormatter().format(_record()))

    assert "exc_info" not in payload


# --- configure_logging(): correction 4 ---


def test_configure_logging_does_not_touch_root_handlers_under_pytest():
    root = logging.getLogger()
    before = list(root.handlers)

    configure_logging()

    assert root.handlers == before, (
        "configure_logging() must no-op under the test runner -- replacing "
        "root.handlers here would clobber pytest's own log capture"
    )


def test_the_suite_itself_is_proof_this_does_not_break_pytest_capture(caplog):
    """If configure_logging() ever stopped no-op'ing under pytest, this
    test's own use of caplog -- which depends on being able to attach a
    handler to the root logger -- would start failing collection-wide,
    not just here. Kept as a direct, explicit check rather than relying
    on that indirect signal alone.
    """
    with caplog.at_level(logging.INFO):
        logging.getLogger("app.test").info("captured fine")

    assert "captured fine" in caplog.text
