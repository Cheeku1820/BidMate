import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session as DbSession

from app.auth.service import user_for_session
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User

COOKIE_NAME = "takeoff_session"

NOT_SIGNED_IN = DomainError("not_signed_in", "Sign in to continue.", status=401)


def current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise NOT_SIGNED_IN
    try:
        session_id = uuid.UUID(raw)
    except ValueError:
        raise NOT_SIGNED_IN
    user = user_for_session(db, session_id)
    if user is None:
        raise NOT_SIGNED_IN
    return user
