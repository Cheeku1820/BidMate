import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.models import Session
from app.auth.passwords import hash_password, verify_password
from app.config import settings
from app.errors import DomainError
from app.identity.models import User


def _invalid_credentials() -> DomainError:
    # A fresh instance every call, never a shared/module-level one. In
    # CPython, raising the same exception object twice appends to its
    # existing __traceback__ rather than replacing it, and each retained
    # frame keeps that frame's locals reachable — including login()'s
    # `password` parameter. A shared instance would leak every failed
    # login's plaintext password for the life of the process (recoverable
    # from a core dump or any error reporter that walks tracebacks) and
    # grow without bound under a credential-stuffing run. Fresh instances
    # also avoid mutating a shared object across concurrent requests.
    return DomainError(
        "invalid_credentials",
        "Those sign-in details were not recognised. Check what you entered and try again.",
        status=401,
    )


# A valid-looking hash to verify against on the "email not found" path, so
# that path pays the same argon2 cost as a real wrong-password check. Never
# used to authenticate anything — computed once at import time from a fixed
# string, not tied to any real account.
_DUMMY_HASH = hash_password("no-such-account-placeholder")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def login(db: DbSession, email: str, password: str) -> Session:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None or user.deactivated_at is not None:
        # Verify against a dummy hash even though there's no real user (or
        # no active one) so this path takes the same ~argon2-verify amount
        # of time as a wrong-password rejection below. Skipping this call
        # makes an unknown email answer in ~1ms against a real email's
        # ~37ms, which lets an attacker enumerate registered addresses by
        # timing alone, despite the identical response body.
        verify_password(password, _DUMMY_HASH)
        raise _invalid_credentials()
    if not verify_password(password, user.password_hash):
        raise _invalid_credentials()

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
    user = db.get(User, session.user_id)
    if user is None or user.deactivated_at is not None:
        # A user deactivated while holding a live session must lose access
        # immediately, not at the end of the session's TTL (up to 12
        # hours). This is the one chokepoint every future route inherits
        # through current_user, so the check belongs here rather than in
        # a future deprovisioning endpoint.
        return None
    return user
