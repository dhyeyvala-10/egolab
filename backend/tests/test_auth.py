from sqlalchemy import select

from egolabs.models import Event, User
from tests.conftest import auth_header, register


def test_first_user_is_the_owner_and_later_users_wait_for_access(client):
    first = register(client, "first@example.com", name="First")
    second = register(client, "second@example.com")
    assert (first["user"]["role"], first["user"]["is_owner"]) == ("admin", True)
    assert first["user"]["name"] == "First"
    assert (second["user"]["role"], second["user"]["is_owner"]) == ("pending", False)
    assert first["token_type"] == "bearer"
    assert first["expires_in"] > 0


def test_register_stores_a_hash_and_records_an_event(client, db):
    res = register(client, "Mixed.Case@Example.com")
    assert res["user"]["email"] == "mixed.case@example.com"
    user = db.scalar(select(User))
    assert user.password_hash.startswith("$argon2")
    assert "correct horse" not in user.password_hash
    event = db.scalar(select(Event).where(Event.type == "user.registered"))
    assert event.entity_id == user.id


def test_register_rejects_duplicate_email_case_insensitively(client):
    register(client, "dup@example.com")
    res = client.post(
        "/api/v1/auth/register", json={"email": "DUP@example.com", "password": "another password"}
    )
    assert res.status_code == 409


def test_register_validates_input(client):
    assert (
        client.post("/api/v1/auth/register", json={"email": "a@b.test", "password": "short"}).status_code
        == 422
    )
    res = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "long enough pw"})
    assert res.status_code == 422


def test_login(client):
    register(client, "login@example.com", password="s3cret-password")
    res = client.post(
        "/api/v1/auth/login", json={"email": "LOGIN@example.com", "password": "s3cret-password"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["email"] == "login@example.com"
    me = client.get("/api/v1/auth/me", headers=auth_header(body))
    assert me.status_code == 200
    assert me.json()["email"] == "login@example.com"


def test_login_rejects_bad_credentials_with_the_same_message(client):
    register(client, "login@example.com", password="s3cret-password")
    wrong = client.post("/api/v1/auth/login", json={"email": "login@example.com", "password": "nope-nope"})
    unknown = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_me_requires_a_valid_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_deactivated_user_cannot_log_in_or_use_token(client, db):
    admin = register(client, "admin@example.com")
    viewer = register(client, "viewer@example.com", password="viewer-password")
    client.patch(
        f"/api/v1/users/{viewer['user']['id']}", json={"is_active": False}, headers=auth_header(admin)
    ).raise_for_status()
    assert client.get("/api/v1/auth/me", headers=auth_header(viewer)).status_code == 403
    res = client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.com", "password": "viewer-password"}
    )
    assert res.status_code == 403
