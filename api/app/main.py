import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.router import router as auth_router
from app.db import get_db
from app.errors import DomainError, domain_error_handler
from app.takeoff.actions import CrossOrgActionError
from app.takeoff.router import PROJECT_NOT_FOUND_CODE, PROJECT_NOT_FOUND_MESSAGE
from app.takeoff.router import router as takeoff_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Takeoff API")
app.add_exception_handler(DomainError, domain_error_handler)


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

    No request-id middleware exists yet in this codebase (the design notes
    one as an architecture goal); this logs whatever `X-Request-Id` header
    is present, or "unset" otherwise, rather than blocking on that
    infrastructure landing first.
    """
    request_id = request.headers.get("x-request-id", "unset")
    logger.warning("CrossOrgActionError reached the HTTP boundary (request_id=%s): %s", request_id, exc)
    return JSONResponse(
        status_code=404,
        content={"detail": {"code": PROJECT_NOT_FOUND_CODE, "message": PROJECT_NOT_FOUND_MESSAGE}},
    )


app.include_router(auth_router)
app.include_router(takeoff_router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("select 1"))
    return {"status": "ok", "database": "ok"}
