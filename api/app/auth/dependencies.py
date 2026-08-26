import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session as DbSession

from app.auth.service import user_for_session
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User

COOKIE_NAME = "takeoff_session"


def _not_signed_in() -> DomainError:
    # A fresh instance every call — see the matching note on
    # app.auth.service._invalid_credentials for why a shared/module-level
    # exception instance is unsafe to raise repeatedly.
    return DomainError("not_signed_in", "Sign in to continue.", status=401)


def current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise _not_signed_in()
    try:
        session_id = uuid.UUID(raw)
    except ValueError:
        raise _not_signed_in()
    user = user_for_session(db, session_id)
    if user is None:
        raise _not_signed_in()
    return user
