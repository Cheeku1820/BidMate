import pytest
from sqlalchemy.exc import IntegrityError

from app.identity.models import Org, User


def test_email_is_unique_across_the_system(db):
    org = Org(name="Meridian Electric")
    db.add(org)
    db.flush()

    db.add(User(org_id=org.id, email="dana@example.com", password_hash="x", name="Dana", color="#23528f"))
    db.flush()

    db.add(User(org_id=org.id, email="dana@example.com", password_hash="y", name="Other", color="#1c6f47"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_external_id_is_nullable_so_an_identity_provider_can_map_later(db):
    org = Org(name="Meridian Electric")
    db.add(org)
    db.flush()

    user = User(org_id=org.id, email="dana@example.com", password_hash="x", name="Dana", color="#23528f")
    db.add(user)
    db.flush()

    assert user.external_id is None
