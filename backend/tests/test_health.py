import pytest

from egolabs.api import health as health_module
from egolabs.db import get_db


def test_health_ok_when_all_dependencies_respond(client, monkeypatch):
    monkeypatch.setattr(health_module, "check_buckets", lambda: None)
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert {k: v["status"] for k, v in body["checks"].items()} == {
        "database": "ok",
        "redis": "ok",
        "storage": "ok",
    }


def test_health_degraded_when_storage_is_missing(client, monkeypatch):
    def missing() -> None:
        raise RuntimeError("bucket egolabs-raw not found")

    monkeypatch.setattr(health_module, "check_buckets", missing)
    body = client.get("/api/v1/health").json()
    assert body["status"] == "degraded"
    assert body["checks"]["storage"]["status"] == "error"
    assert "egolabs-raw" in body["checks"]["storage"]["detail"]


def test_health_503_when_database_is_down(client, monkeypatch):
    monkeypatch.setattr(health_module, "check_buckets", lambda: None)

    class BrokenSession:
        def execute(self, *_: object) -> None:
            raise ConnectionError("connection refused")

    client.app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        res = client.get("/api/v1/health")
    finally:
        client.app.dependency_overrides.clear()
    assert res.status_code == 503
    assert res.json()["status"] == "down"


@pytest.mark.parametrize("path", ["/api/v1/openapi.json"])
def test_openapi_schema_is_served(client, path):
    schema = client.get(path).json()
    assert "/api/v1/overview" in schema["paths"]
    assert "OverviewResponse" in schema["components"]["schemas"]
