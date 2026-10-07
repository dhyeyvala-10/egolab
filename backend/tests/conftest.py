"""
Tests run against a real PostgreSQL database (JSONB, CHECK constraints, advisory locks).

TEST_DATABASE_URL points at a database the tests may drop and recreate; it defaults to
`egolabs_test` on the local dev server. The schema is built with Alembic, so every run also
exercises the migrations from an empty database.
"""

import os
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://egolabs:egolabs@localhost:5432/egolabs_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-0123456789abcdef")


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# In-process S3 (moto) so storage tests need no MinIO container. Set TEST_S3_ENDPOINT_URL to use a real one.
_moto = None
if "TEST_S3_ENDPOINT_URL" in os.environ:
    os.environ["S3_ENDPOINT_URL"] = os.environ["TEST_S3_ENDPOINT_URL"]
else:
    from moto.server import ThreadedMotoServer

    _port = _free_port()
    _moto = ThreadedMotoServer(ip_address="127.0.0.1", port=_port, verbose=False)
    _moto.start()
    os.environ["S3_ENDPOINT_URL"] = f"http://127.0.0.1:{_port}"
    os.environ["S3_ACCESS_KEY"] = "testing"
    os.environ["S3_SECRET_KEY"] = "testing"
os.environ.pop("S3_PUBLIC_ENDPOINT_URL", None)
# Most tests sign in with a password (people sign in with Google; see test_google_auth.py for that).
os.environ["PASSWORD_LOGIN"] = "true"
for _var in (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_AUTHORIZE_URL",
    "GOOGLE_TOKEN_URL",
    "GOOGLE_JWKS_URL",
):
    os.environ.pop(_var, None)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from egolabs.config import get_settings  # noqa: E402
from egolabs.db import get_engine, get_sessionmaker  # noqa: E402
from egolabs.models import Base  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def alembic_config() -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    return cfg


def _recreate_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    from egolabs import storage

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    for fn in (storage.get_s3_client, storage.get_transfer_client, storage.get_presign_client):
        fn.cache_clear()
    storage.ensure_buckets()
    _recreate_database()
    command.upgrade(alembic_config(), "head")
    yield
    get_engine().dispose()
    if _moto is not None:
        _moto.stop()


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    # Most tests have annotators and reviewers start processing; out of the box only the admin may
    # (tests/test_access.py covers that default by removing this setting).
    with get_engine().begin() as conn:
        conn.execute(text("INSERT INTO app_settings (key, value) VALUES ('processing_by', '\"editors\"')"))
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        # Reference data the migrations insert: the built-in movement classes.
        from egolabs.cv.movement.classes import rows
        from egolabs.models import MovementClass

        conn.execute(MovementClass.__table__.insert(), [{"id": uuid.uuid4(), **r} for r in rows()])


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    from egolabs.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture job ids sent to Celery instead of talking to a broker."""
    from egolabs.worker import tasks

    sent: list[str] = []

    def fake_delay(job_id: str) -> SimpleNamespace:
        sent.append(job_id)
        return SimpleNamespace(id=f"celery-{len(sent)}")

    monkeypatch.setattr(tasks.run_job_task, "delay", fake_delay)
    return sent


def drain(enqueued: list[str]) -> None:
    """Run queued jobs in order, including jobs they queue, as the worker would."""
    from egolabs.worker import tasks  # noqa: F401  (registers handlers)
    from egolabs.worker.runtime import run_job

    done = 0
    while done < len(enqueued):
        run_job(enqueued[done])
        done += 1


def register(client: TestClient, email: str, password: str = "correct horse battery", **extra) -> dict:
    res = client.post("/api/v1/auth/register", json={"email": email, "password": password, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def auth_header(token_response: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_response['access_token']}"}


@pytest.fixture
def admin(client: TestClient) -> dict:
    return register(client, "admin@example.com", name="Ada Admin")


def user_with_role(client: TestClient, admin: dict, email: str, role: str, **extra) -> dict:
    """Register a user and have the admin give them `role`. Returns the token response."""
    token = register(client, email, **extra)
    res = client.patch(
        f"/api/v1/users/{token['user']['id']}", json={"role": role}, headers=auth_header(admin)
    )
    assert res.status_code == 200, res.text
    return token


@pytest.fixture
def viewer(client: TestClient, admin: dict) -> dict:
    return user_with_role(client, admin, "viewer@example.com", "viewer")


@pytest.fixture
def annotator(client: TestClient, admin: dict) -> dict:
    return user_with_role(client, admin, "annotator@example.com", "annotator", name="Ann Otator")
