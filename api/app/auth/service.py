import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.models import Session
from app.auth.passwords import verify_password
from app.config import settings
from app.errors import DomainError
from app.identity.models import User

# Deliberately does not name which of email or password was wrong, and
# avoids the literal word "password" so the failure copy can never be
# mistaken for a hint about which field to fix.
INVALID = DomainError(
    "invalid_credentials",
    "Those sign-in details were not recognised. Check what you entered and try again.",
    status=401,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def login(db: DbSession, email: str, password: str) -> Session:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None or user.deactivated_at is not None:
        raise INVALID
    if not verify_password(password, user.password_hash):
        raise INVALID

    session = Session(user_id=user.id, expires_at=_now() + timedelta(hours=settings.session_ttl_hours))
    db.add(session)
    db.flush()
    return session


def logout(db: DbSession, session_id: uuid.UUID) -> None:
    session = db.get(Session, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = _now()
        db.flush()


def user_for_session(db: DbSession, session_id: uuid.UUID) -> User | None:
    session = db.get(Session, session_id)
    if session is None or session.revoked_at is not None or session.expires_at < _now():
        return None
    return db.get(User, session.user_id)
