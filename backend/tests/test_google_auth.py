"""Signing in with Google, against a local stand-in for Google's endpoints (tests/fake_google.py): the
real code exchange over HTTP, PKCE, and ID token verification with Google's published keys."""

from collections.abc import Iterator

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from egolabs.config import get_settings
from egolabs.models import Event, User
from tests.conftest import auth_header, register
from tests.fake_google import FakeGoogle, pkce_pair

REDIRECT = "http://localhost:3000/auth/google/callback"


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGoogle]:
    fake = FakeGoogle().start()
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", fake.client_id)
    monkeypatch.setattr(s, "google_client_secret", SecretStr(fake.client_secret))
    monkeypatch.setattr(s, "google_authorize_url", f"{fake.url}/authorize")
    monkeypatch.setattr(s, "google_token_url", f"{fake.url}/token")
    monkeypatch.setattr(s, "google_jwks_url", f"{fake.url}/certs")
    yield fake
    fake.stop()


def sign_in(client, google: FakeGoogle, verifier: str | None = None, redirect: str = REDIRECT, **claims):
    """Do what the web app's callback does with the code Google sends back."""
    good_verifier, challenge = pkce_pair()
    code = google.issue_code(REDIRECT, challenge, **claims)
    return client.post("/api/v1/auth/google", json={"code": code, "redirect_uri": redirect,
                                                    "code_verifier": verifier or good_verifier})  # fmt: skip


def test_config_says_whether_google_sign_in_is_set_up(client, google, monkeypatch):
    res = client.get("/api/v1/auth/google").json()
    assert res == {"enabled": True, "client_id": google.client_id, "authorize_url": f"{google.url}/authorize"}
    assert "secret" not in str(res)
    monkeypatch.setattr(get_settings(), "google_client_secret", None)
    assert client.get("/api/v1/auth/google").json()["enabled"] is False
    res = sign_in(client, google)
    assert res.status_code == 503 and res.json()["detail"] == "Google sign-in isn't set up"


def test_first_google_account_is_the_owner_and_later_ones_wait_for_access(client, db, google):
    first = sign_in(client, google)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["user"] | {"id": None, "created_at": None, "last_sign_in_at": None, "last_seen_at": None} == {
        "id": None, "email": "ada@example.com", "name": "Ada Lovelace", "role": "admin", "is_active": True,
        "is_owner": True, "created_at": None, "last_sign_in_at": None, "last_seen_at": None,
    }  # fmt: skip
    me = client.get("/api/v1/auth/me", headers=auth_header(body)).json()
    assert me["email"] == "ada@example.com"

    # The code went to Google with the client secret, our redirect URI and the PKCE verifier.
    sent = google.token_requests[-1]
    assert sent["client_secret"] == google.client_secret and sent["redirect_uri"] == REDIRECT
    assert sent["grant_type"] == "authorization_code" and len(sent["code_verifier"]) >= 43

    second = sign_in(client, google, sub="2002", email="Grace@Example.com", name="Grace Hopper").json()
    assert (second["user"]["email"], second["user"]["role"]) == ("grace@example.com", "pending")
    users = {u.email: u for u in db.scalars(select(User))}
    assert users["ada@example.com"].google_sub == "1001" and users["ada@example.com"].password_hash is None
    events = db.scalars(select(Event).where(Event.type == "user.registered")).all()
    assert sorted(e.data["via"] for e in events) == ["google", "google"]


def test_signing_in_again_finds_the_same_account(client, db, google):
    first = sign_in(client, google).json()
    # Google's id (`sub`) is what identifies the account, even if the email on it changes.
    again = sign_in(client, google, email="ada.l@example.com", name="Ada").json()
    assert again["user"]["id"] == first["user"]["id"]
    assert db.scalar(select(User).where(User.id == first["user"]["id"])).name == "Ada Lovelace"
    assert len(db.scalars(select(User)).all()) == 1


def test_an_existing_account_is_linked_by_its_verified_email(client, db, google):
    admin = register(client, "ada@example.com", name="Ada")
    res = sign_in(client, google).json()
    assert res["user"]["id"] == admin["user"]["id"] and res["user"]["role"] == "admin"
    assert db.scalar(select(User)).google_sub == "1001"
    # The same email from another Google account doesn't take it over.
    other = sign_in(client, google, sub="9999")
    assert other.status_code == 409


@pytest.mark.parametrize(
    ("claims", "message"),
    [
        ({"email_verified": False}, "Your Google account's email address isn't verified."),
        ({"aud": "someone-elses-client"}, "Google's sign-in token isn't valid. Try again."),
        ({"iss": "https://evil.example.com"}, "Google's sign-in token isn't valid. Try again."),
        ({"exp": 1_000_000_000}, "Google's sign-in token isn't valid. Try again."),
    ],
)
def test_tokens_google_would_not_vouch_for_are_refused(client, db, google, claims, message):
    res = sign_in(client, google, **claims)
    assert res.status_code == 400 and res.json()["detail"] == message
    assert db.scalar(select(User)) is None


def test_a_token_not_signed_by_google_is_refused(client, db, google, monkeypatch):
    impostor = FakeGoogle()  # a different key, but the same key id
    impostor.kid = google.kid
    monkeypatch.setattr(google, "id_token", impostor.id_token)
    res = sign_in(client, google)
    assert res.status_code == 400 and res.json()["detail"] == "Google's sign-in token isn't valid. Try again."
    assert db.scalar(select(User)) is None


def test_the_code_only_works_with_its_verifier_redirect_and_once(client, google):
    assert sign_in(client, google, verifier="x" * 43).status_code == 400
    assert sign_in(client, google, redirect="http://localhost:3000/elsewhere").status_code == 400
    verifier, challenge = pkce_pair()
    code = google.issue_code(REDIRECT, challenge)
    body = {"code": code, "redirect_uri": REDIRECT, "code_verifier": verifier}
    assert client.post("/api/v1/auth/google", json=body).status_code == 200
    replay = client.post("/api/v1/auth/google", json=body)
    assert replay.status_code == 400 and replay.json()["detail"].startswith(
        "Google didn't accept the sign-in"
    )


def test_google_being_unreachable_is_reported(client, google, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_token_url", "http://127.0.0.1:9/token")
    res = sign_in(client, google)
    assert (
        res.status_code == 400
        and res.json()["detail"] == "Couldn't reach Google to finish signing in. Try again."
    )


def test_a_deactivated_account_cannot_sign_in_with_google(client, db, google):
    sign_in(client, google)
    sign_in(client, google, sub="2002", email="grace@example.com", name="Grace Hopper")
    user = db.scalar(select(User).where(User.email == "grace@example.com"))
    user.is_active = False
    db.commit()
    res = sign_in(client, google, sub="2002", email="grace@example.com", name="Grace Hopper")
    assert res.status_code == 403 and res.json()["detail"] == "Account is deactivated"


def test_password_sign_in_is_off_unless_turned_on(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "password_login", False)
    for path, body in [("/api/v1/auth/register", {"email": "a@example.com", "password": "long enough"}),
                       ("/api/v1/auth/login", {"email": "a@example.com", "password": "long enough"})]:  # fmt: skip
        res = client.post(path, json=body)
        assert res.status_code == 404
        assert res.json()["detail"] == "Email and password sign-in is turned off; sign in with Google"


def test_a_google_account_has_no_password_to_sign_in_with(client, google):
    sign_in(client, google)
    res = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "anything at all"})
    assert res.status_code == 401


def test_scripts_get_a_token_for_an_existing_account(client, google, capsys):
    from egolabs import token

    user = sign_in(client, google).json()["user"]
    assert token.main(["ADA@example.com"]) == 0
    printed = capsys.readouterr().out.strip()
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {printed}"}).json()["id"]
        == user["id"]
    )
    assert token.main(["nobody@example.com"]) == 1
    assert "Sign in with Google once" in capsys.readouterr().err
