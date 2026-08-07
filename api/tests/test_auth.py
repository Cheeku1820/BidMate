import pytest

from app.auth.passwords import hash_password
from app.identity.models import Org, User


@pytest.fixture
def dana(db):
    org = Org(name="Meridian Electric")
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email="dana@example.com",
        password_hash=hash_password("correct-horse"),
        name="Dana Whitfield",
        color="#23528f",
    )
    db.add(user)
    db.flush()
    return user


def test_login_sets_a_session_cookie_and_returns_the_user(client, dana):
    response = client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})

    assert response.status_code == 200
    assert response.json()["name"] == "Dana Whitfield"
    assert "takeoff_session" in response.cookies


def test_login_with_a_wrong_password_is_refused_without_saying_which_field_was_wrong(client, dana):
    response = client.post("/api/auth/login", json={"email": "dana@example.com", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"
    assert "password" not in response.json()["detail"]["message"].lower()


def test_me_requires_a_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_the_session(client, dana):
    client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
