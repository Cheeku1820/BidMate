"""create_admin.py -- creates an org and one user, and nothing else.

This replaces the demo seed (app/seed.py), which loaded a twelve-item
fixture takeoff. That fixture is gone: every row in the product now comes
from a document an estimator actually uploaded.

What could not go with it is account creation. A freshly migrated
database contains no user, so there is no credential the login screen
will accept. This is that step, and only that step -- no project, no
sheets, no items.

No default password: credentials are arguments, and main() exits loudly
if the environment does not supply them.
"""
from __future__ import annotations

import os
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.identity.models import Org, User

# The estimator's presence avatar color, shown in the top bar and on
# remote-selection rings. Every account created through this CLI gets the
# same fixed color -- there is no palette or picker at signup, and this
# matches the color the old demo seed (app/seed.py) used for its one user.
_DEFAULT_USER_COLOR = "#23528f"


def create_admin(db: DbSession, *, email: str, password: str, org_name: str) -> User:
    normalized = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == normalized))
    if existing is not None:
        raise ValueError(f"A user with the email {normalized!r} already exists.")

    org = Org(id=uuid.uuid4(), name=org_name)
    db.add(org)

    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        email=normalized,
        name=normalized.split("@")[0],
        password_hash=hash_password(password),
        color=_DEFAULT_USER_COLOR,
    )
    db.add(user)
    return user


def main() -> None:
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    org_name = os.environ.get("ADMIN_ORG", "My electrical company")
    if not email or not password:
        raise SystemExit(
            "Set ADMIN_EMAIL and ADMIN_PASSWORD to create the first account. "
            "There is no default password."
        )
    db = SessionLocal()
    try:
        user = create_admin(db, email=email, password=password, org_name=org_name)
        db.commit()
        print(f"Created {user.email} in org {org_name!r}. Sign in with that email and password.", file=sys.stderr)
    except ValueError as exc:
        db.rollback()
        raise SystemExit(str(exc)) from None
    finally:
        db.close()


if __name__ == "__main__":
    main()
