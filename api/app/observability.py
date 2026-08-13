"""Request-id middleware and structured JSON logging.

Every response carries an `X-Request-Id` header, and every log line
written while handling that request carries the same id via a
`ContextVar` -- so a support conversation ("it failed, here's the
reference on screen") starts with something greppable in the logs,
without the estimator ever seeing a stack trace, a model name, or any
other processing internal (CLAUDE.md's rule that internals stop at the
product boundary applies to error copy too).

This module is deliberately small and self-contained -- `main.py` wires
it in with two lines (`configure_logging()` and
`app.add_middleware(RequestIdMiddleware)`) and nothing else in the app
imports from it except `request_id_var`, used once by
`main.cross_org_action_error_handler` to log the request's real id
instead of trusting whatever header a caller sent.

Corrections applied here relative to the plan's sketch
(docs/superpowers/plans/2026-08-07-backend-spine.md, "Task 14") --
see task-14-brief.md for the full reasoning:

1. The sketch's `JsonFormatter` emitted only level/message/logger/
   request_id, which meant `logging.exception("unhandled error")` --
   the 500 path's only logging call, and the entire reason to call
   `.exception()` instead of `.error()` -- lost its traceback outright.
   `exc_info` is now included when present, and a `timestamp` is added.
2. The sketch trusted an inbound `X-Request-Id` header
   (`request.headers.get("x-request-id") or uuid4()...`) straight into
   every log line for that request. With a JSON formatter that is a
   log-forging vector (embedded quotes/braces, or newlines against any
   line-oriented log consumer), and it lets an attacker force two
   unrelated requests to share one correlation id. There is no trusted
   upstream proxy in front of this API yet, so the id is always
   generated server-side; an inbound header is read nowhere in this
   module.
"""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Empty default (rather than None) so a log line emitted outside any
# request -- at import time, say -- serializes a plain "" instead of
# `null` or raising, and so JsonFormatter never needs a null check here.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    """One JSON object per log line: timestamp, level, message, logger
    name, the current request id, and -- when the record carries one --
    a formatted traceback.

    `record.exc_info` is only ever non-None on the small number of calls
    that pass `exc_info=True` or use `logging.exception(...)`; nothing
    else in this codebase currently does either, but a future caller
    that does gets the traceback captured automatically, for free,
    without needing to know this formatter exists.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    """Route the root logger through `JsonFormatter`, writing to stdout.

    No-ops under pytest. `root.handlers = [handler]` (the sketch's
    approach, kept here for a real server process) *replaces* whatever
    is already attached to the root logger -- fine when nothing else
    owns it, but pytest's own logging plugin attaches its capture
    machinery to that same root logger for the whole session the moment
    `conftest.py` does `from app.main import app` during collection. If
    this function ran unconditionally at that import, it would tear out
    pytest's capture handler before a single test runs, and every one of
    this suite's ~200 tests would get noticeably noisier `-q` output (or
    worse, break `caplog` for tests that rely on it) for a code path a
    test run never actually needs -- production logging is exercised by
    calling this from a real server process, not from the test runner.

    `"pytest" in sys.modules` is true from the moment the pytest process
    starts (it imports itself before doing anything else, including
    collecting `conftest.py`), which makes it a reliable, standard guard
    for "is this process the test runner" without needing a bespoke
    environment variable nobody else in this codebase sets.
    """
    if "pytest" in sys.modules:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generate a request id, make it available to every log line
    written while handling this request, and attach it to the response.

    Registration order matters and is not just a style preference: this
    middleware has to be registered *before* `main.py`'s
    `no_shared_caching` middleware, because `Starlette.add_middleware`
    prepends to `user_middleware` and Starlette builds its ASGI stack so
    the most-recently-added user middleware ends up outermost. If this
    middleware were outermost, a response it synthesizes here for an
    unhandled exception would never pass back through
    `no_shared_caching`'s post-processing, and a bid-relevant error page
    would ship without `Cache-Control: private, no-store` -- registering
    this one first makes it the innermost of the two, so its response
    (synthesized or passed through) always flows back out through
    `no_shared_caching` afterward. See task-14-brief.md, correction 5,
    and `tests/test_observability.py`'s structural check on `main.app`.

    An unexpected error's response copy names a recovery action and the
    request id, and never the exception text -- `str(exc)` never appears
    anywhere in the response, only in the server-side log line, so a
    support conversation can start from the id without the estimator
    ever seeing processing internals.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:12]
        request_id_var.set(request_id)
        try:
            response = await call_next(request)
        except Exception:
            logging.exception("unhandled error")
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "unexpected_error",
                        "message": (
                            "That did not complete. Try again, and mention this "
                            "reference if it keeps happening."
                        ),
                        "request_id": request_id,
                    }
                },
            )
        response.headers["X-Request-Id"] = request_id
        return response
