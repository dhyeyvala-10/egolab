import json
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

import numpy as np
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from egolabs.config import get_settings


def _json_default(value: Any) -> Any:
    """JSON for numpy values (the CV code computes with numpy, and e.g. `int64` isn't JSON on its own)."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def dumps(value: Any) -> str:
    return json.dumps(value, default=_json_default)


@lru_cache
def get_engine() -> Engine:
    # Every JSONB column is written with `dumps`, so numpy numbers from the CV code are stored as plain numbers.
    return create_engine(get_settings().database_url, pool_pre_ping=True, json_serializer=dumps)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with get_sessionmaker()() as session:
        yield session
