"""The owner's settings, changed in the app (Settings → Limits) and kept in `app_settings`.

- `upload_max_bytes`: an upload bigger than this waits for the owner before any of it is sent.
- `video_max_seconds`: a video longer than this is held; nothing processes it until the owner allows it.
- `processing_by`: who may start processing (pipelines, their runs and schedules, CV runs, auto annotation,
  dataset versions and exports): `owner` (only the owner) or `editors` (annotators and reviewers too).

`None` for a limit means no limit. The owner is never held by their own limits.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from egolabs.models import AppSetting

ProcessingBy = Literal["owner", "editors"]


class Limits(BaseModel):
    upload_max_bytes: int | None = Field(default=1_000_000_000, ge=1, description="None: no limit")
    video_max_seconds: float | None = Field(default=None, gt=0, description="None: no limit")
    processing_by: ProcessingBy = "owner"


_KEYS = tuple(Limits.model_fields)


def get(db: Session) -> Limits:
    rows = {r.key: r.value for r in db.query(AppSetting).filter(AppSetting.key.in_(_KEYS))}
    return Limits(**{k: v for k, v in rows.items()})


def put(db: Session, values: dict[str, Any], by: uuid.UUID) -> Limits:
    """Store the given settings (validated together with the rest); the caller commits."""
    merged = Limits(**{**get(db).model_dump(), **values})
    now = datetime.now(UTC)
    for key in values:
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key)
            db.add(row)
        row.value, row.updated_at, row.updated_by = getattr(merged, key), now, by
    return merged
