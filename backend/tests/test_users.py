from sqlalchemy import select

from egolabs.models import Event, SignIn
from tests.conftest import auth_header, register


def test_list_users_is_admin_only_and_lists_the_owner_then_people_waiting(client, admin, viewer):
    assert client.get("/api/v1/users", headers=auth_header(viewer)).status_code == 403
    assert client.get("/api/v1/users").status_code == 401

    register(client, "third@example.com")
    res = client.get("/api/v1/users", params={"limit": 2, "offset": 0}, headers=auth_header(admin))
    assert res.status_code == 200
    page = res.json()
    assert page["total"] == 3
    assert [u["email"] for u in page["items"]] == ["admin@example.com", "third@example.com"]
    rest = client.get("/api/v1/users", params={"limit": 2, "offset": 2}, headers=auth_header(admin)).json()
    assert [u["email"] for u in rest["items"]] == ["viewer@example.com"]


def test_admin_gives_a_role_and_it_is_logged(client, db, admin):
    newcomer = register(client, "new@example.com")
    res = client.patch(
        f"/api/v1/users/{newcomer['user']['id']}", json={"role": "annotator"}, headers=auth_header(admin)
    )
    assert res.status_code == 200
    assert res.json()["role"] == "annotator"
    event = db.scalar(select(Event).where(Event.type == "user.updated"))
    assert event.data == {"role": {"from": "pending", "to": "annotator"}}
    assert event.message == "new@example.com: role annotator"
    assert str(event.actor_id) == admin["user"]["id"]


def test_non_admin_cannot_change_roles(client, admin, viewer):
    res = client.patch(
        f"/api/v1/users/{viewer['user']['id']}", json={"role": "reviewer"}, headers=auth_header(viewer)
    )
    assert res.status_code == 403


def test_nobody_can_be_made_admin_and_the_owner_cannot_be_changed(client, admin, viewer):
    headers = auth_header(admin)
    res = client.patch(f"/api/v1/users/{viewer['user']['id']}", json={"role": "admin"}, headers=headers)
    assert res.status_code == 422
    owner_id = admin["user"]["id"]
    for body in ({"role": "viewer"}, {"is_active": False}):
        res = client.patch(f"/api/v1/users/{owner_id}", json=body, headers=headers)
        assert res.status_code == 409 and res.json()["detail"] == "The owner's account can't be changed"


def test_taking_access_away_and_blocking(client, admin, viewer):
    headers, vid = auth_header(admin), viewer["user"]["id"]
    assert client.get("/api/v1/overview", headers=auth_header(viewer)).status_code == 200

    client.patch(f"/api/v1/users/{vid}", json={"role": "pending"}, headers=headers).raise_for_status()
    res = client.get("/api/v1/overview", headers=auth_header(viewer))
    assert (
        res.status_code == 403
        and res.json()["detail"] == "Your account is waiting for the admin to give you access"
    )
    assert client.get("/api/v1/auth/me", headers=auth_header(viewer)).json()["role"] == "pending"

    client.patch(
        f"/api/v1/users/{vid}", json={"role": "viewer", "is_active": False}, headers=headers
    ).raise_for_status()
    res = client.get("/api/v1/auth/me", headers=auth_header(viewer))
    assert res.status_code == 403 and res.json()["detail"] == "Account is deactivated"


def test_update_unknown_user_is_404(client, admin):
    res = client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000",
        json={"role": "viewer"},
        headers=auth_header(admin),
    )
    assert res.status_code == 404


def test_update_rejects_unknown_role(client, admin, viewer):
    res = client.patch(
        f"/api/v1/users/{viewer['user']['id']}", json={"role": "owner"}, headers=auth_header(admin)
    )
    assert res.status_code == 422


def test_every_sign_in_is_kept_with_where_it_came_from(client, db, admin):
    client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct horse battery"},
        headers={"user-agent": "Firefox/140", "cf-connecting-ip": "203.0.113.9"},
    ).raise_for_status()
    rows = db.scalars(select(SignIn).order_by(SignIn.created_at)).all()
    assert [r.method for r in rows] == ["password", "password"]  # registering signs in too
    assert (rows[-1].ip, rows[-1].user_agent) == ("203.0.113.9", "Firefox/140")

    page = client.get("/api/v1/users/sign-ins", headers=auth_header(admin)).json()
    assert page["total"] == 2
    assert page["items"][0] | {"id": None, "user_id": None, "created_at": None} == {
        "id": None, "user_id": None, "created_at": None, "user_email": "admin@example.com", "user_name": "Ada Admin",
        "method": "password", "ip": "203.0.113.9", "user_agent": "Firefox/140",
    }  # fmt: skip
    me = client.get("/api/v1/auth/me", headers=auth_header(admin)).json()
    assert me["last_sign_in_at"] is not None and me["last_seen_at"] is not None


def test_the_admin_sees_everything_everyone_did(client, admin, viewer):
    other = register(client, "someone@example.com")
    page = client.get("/api/v1/users/activity", headers=auth_header(admin)).json()
    registered = [e for e in page["items"] if e["type"] == "user.registered"]
    assert {e["actor_email"] for e in registered} == {
        "admin@example.com",
        "viewer@example.com",
        "someone@example.com",
    }
    only = client.get(
        "/api/v1/users/activity", params={"user_id": other["user"]["id"]}, headers=auth_header(admin)
    ).json()
    assert [e["message"] for e in only["items"]] == [
        "User registered: someone@example.com (waiting for access)"
    ]
    assert client.get("/api/v1/users/activity", headers=auth_header(viewer)).status_code == 403
    assert client.get("/api/v1/users/sign-ins", headers=auth_header(viewer)).status_code == 403
