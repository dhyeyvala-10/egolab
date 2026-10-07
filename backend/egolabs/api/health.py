from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Response, status
from redis import Redis
from sqlalchemy import text

from egolabs import __version__
from egolabs.api.deps import DbSession
from egolabs.config import get_settings
from egolabs.schemas import HealthCheck, HealthResponse
from egolabs.storage import check_buckets

router = APIRouter(tags=["health"])


def _check(fn: Callable[[], Any]) -> HealthCheck:
    try:
        fn()
        return HealthCheck(status="ok")
    except Exception as exc:  # health reports any failure
        return HealthCheck(status="error", detail=f"{type(exc).__name__}: {exc}"[:300])


@router.get("/health", response_model=HealthResponse)
def health(db: DbSession, response: Response) -> HealthResponse:
    """Liveness of the API and its dependencies. 503 when the database is unreachable."""
    settings = get_settings()
    checks = {
        "database": _check(lambda: db.execute(text("SELECT 1"))),
        "redis": _check(lambda: Redis.from_url(settings.redis_url, socket_timeout=2).ping()),
        "storage": _check(check_buckets),
    }
    if checks["database"].status == "error":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall = "down"
    elif any(c.status == "error" for c in checks.values()):
        overall = "degraded"
    else:
        overall = "ok"
    return HealthResponse(status=overall, version=__version__, checks=checks)
