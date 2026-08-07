import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session as DbSession

from app.auth import service
from app.auth.dependencies import COOKIE_NAME, current_user
from app.auth.schemas import LoginRequest, UserOut
from app.config import settings
from app.db import get_db
from app.identity.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: DbSession = Depends(get_db)) -> User:
    session = service.login(db, body.email, body.password)
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        str(session.id),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
    )
    return db.get(User, session.user_id)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)) -> None:
    """Reads the cookie directly rather than depending on current_user, so
    signing out of an already-expired session still clears the cookie."""
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        try:
            service.logout(db, uuid.UUID(raw))
            db.commit()
        except ValueError:
            pass
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
