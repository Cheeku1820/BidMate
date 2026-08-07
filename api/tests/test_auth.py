from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import Session as AuthSession
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
    login_response = client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})
    session_id = login_response.cookies["takeoff_session"]
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    # /logout clears the cookie from the client's jar via delete_cookie, so
    # a follow-up request sent with no cookie at all would pass this test
    # even if service.logout did nothing server-side. Resend the session
    # id explicitly to prove the session itself was revoked, not just the
    # cookie forgotten.
    client.cookies.set("takeoff_session", session_id)
    assert client.get("/api/auth/me").status_code == 401


def test_login_with_an_unknown_email_is_refused_the_same_way(client):
    response = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


def test_expired_session_is_rejected(client, db, dana):
    session = AuthSession(
        user_id=dana.id,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(session)
    db.flush()

    client.cookies.set("takeoff_session", str(session.id))
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_deactivated_user_loses_access_immediately_even_with_a_live_session(client, db, dana):
    client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})
    assert client.get("/api/auth/me").status_code == 200

    dana.deactivated_at = datetime.now(timezone.utc)
    db.flush()

    assert client.get("/api/auth/me").status_code == 401


def test_malformed_cookie_value_is_rejected(client):
    client.cookies.set("takeoff_session", "not-a-uuid")
    response = client.get("/api/auth/me")

    assert response.status_code == 401
