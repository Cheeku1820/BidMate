import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.router import router as auth_router
from app.collab.router import router as collab_router
from app.db import get_db
from app.errors import DomainError, domain_error_handler
from app.observability import RequestIdMiddleware, configure_logging, request_id_var
from app.takeoff.actions import CrossOrgActionError
from app.takeoff.mutations import router as takeoff_mutations_router
from app.takeoff.pricing_router import router as pricing_router
from app.takeoff.router import PROJECT_NOT_FOUND_CODE, PROJECT_NOT_FOUND_MESSAGE
from app.takeoff.router import router as takeoff_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Takeoff API")
app.add_exception_handler(DomainError, domain_error_handler)

configure_logging()
# Registered before no_shared_caching below, on purpose -- see
# RequestIdMiddleware's docstring (app/observability.py) for why the
# order isn't interchangeable: this middleware has to sit *inside*
# no_shared_caching so a synthesized 500 still gets its cache headers.
app.add_middleware(RequestIdMiddleware)


@app.exception_handler(CrossOrgActionError)
async def cross_org_action_error_handler(request: Request, exc: CrossOrgActionError) -> JSONResponse:
    """Defence in depth, not the primary gate.

    `app.takeoff.router.load_project` already refuses a cross-org request
    for every project-scoped route before a service function is ever
    called, so this should be unreachable over HTTP -- if it fires, a gate
    is missing somewhere and that is worth knowing about loudly, hence the
    warning-level log rather than a silent catch.

    Answers with the identical 404 `load_project` raises, not a 403:
    `load_project` returns that specific 404 so a cross-org probe cannot
    confirm a project exists under a guessed id, and a 403 surfacing from
    this deeper layer would hand back exactly the confirmation that 404
    exists to withhold. Consistency between the two paths is the security
    property, which is why the message is imported from `router.py` rather
    than retyped here.

    Logs `request_id_var`'s value (app/observability.py), not the raw
    `X-Request-Id` request header this originally read before
    `RequestIdMiddleware` existed. The two now differ on purpose:
    `RequestIdMiddleware` never trusts an inbound header into anything
    that reaches a log line or a response -- it generates the id
    server-side instead -- so logging the header here would put
    unvalidated, attacker-controlled text on a security-relevant log
    path (a request that just hit an authorization gate), exactly the
    log-forging vector `RequestIdMiddleware` exists to close everywhere
    else. The context var carries the same id this request's response
    is stamped with, set before this handler ever runs.
    """
    request_id = request_id_var.get() or "unset"
    logger.warning("CrossOrgActionError reached the HTTP boundary (request_id=%s): %s", request_id, exc)
    return JSONResponse(
        status_code=404,
        content={"detail": {"code": PROJECT_NOT_FOUND_CODE, "message": PROJECT_NOT_FOUND_MESSAGE}},
    )


@app.middleware("http")
async def no_shared_caching(request: Request, call_next):
    """`Cache-Control: private, no-store` and `Vary: Cookie` on every
    response.

    `/snapshot` carries `undo_label`/`undo_by` -- competitor-readable bid
    progress, per Task 10's review -- and every route in this API is
    either tenant-scoped or an auth boundary. A session cookie alone does
    not make a response private to a *shared* cache under RFC 7234: a
    proxy keyed on URL alone is free to serve one tenant's 200 to the next
    caller unless told otherwise, and `/snapshot`'s `ETag` makes that
    likelier rather than safer -- it is exactly the signal that says "this
    is cacheable and revalidatable" to a cache that doesn't know the
    response is per-tenant. Applied globally via middleware rather than
    per-route: there is no public, safely-shared content anywhere in this
    API to carve an exception for, so a route that forgets to opt in is
    not a risk here the way it would be on a mixed public/private surface.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"
    return response


app.include_router(auth_router)
app.include_router(takeoff_router)
app.include_router(takeoff_mutations_router)
app.include_router(pricing_router)
app.include_router(collab_router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("select 1"))
    return {"status": "ok", "database": "ok"}
