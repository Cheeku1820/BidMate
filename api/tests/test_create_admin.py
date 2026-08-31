"""app/create_admin.py -- the only account-creation path, replacing the
demo seed. It creates an org and a user and nothing else: no project, no
sheets, no items. A migrated database otherwise has no user and the login
screen cannot be passed.
"""
import pytest
from sqlalchemy import func, select

from app.create_admin import create_admin
from app.identity.models import Org, User
from app.takeoff.models import Item, Project, Sheet


def test_create_admin_creates_an_org_and_a_user(db):
    user = create_admin(db, email="you@example.com", password="correct-horse", org_name="Meridian Electric")
    db.flush()
    assert user.email == "you@example.com"
    assert db.get(Org, user.org_id).name == "Meridian Electric"


def test_create_admin_creates_no_project_data(db):
    """This is account creation, not a fixture. Anything else it wrote
    would be the seed data this slice exists to remove."""
    create_admin(db, email="you@example.com", password="correct-horse", org_name="Meridian Electric")
    db.flush()
    assert db.scalar(select(func.count()).select_from(Project)) == 0
    assert db.scalar(select(func.count()).select_from(Sheet)) == 0
    assert db.scalar(select(func.count()).select_from(Item)) == 0


def test_create_admin_stores_a_hashed_password(db):
    user = create_admin(db, email="you@example.com", password="correct-horse", org_name="Meridian")
    db.flush()
    assert "correct-horse" not in (user.password_hash or "")


def test_create_admin_refuses_a_duplicate_email(db):
    create_admin(db, email="you@example.com", password="correct-horse", org_name="Meridian")
    db.flush()
    with pytest.raises(ValueError, match="already exists"):
        create_admin(db, email="you@example.com", password="another-one", org_name="Meridian")
