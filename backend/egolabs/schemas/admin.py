import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from egolabs.app_settings import ProcessingBy


class LimitsUpdate(BaseModel):
    """Only the fields sent change. A limit of null means no limit."""

    upload_max_bytes: int | None = Field(default=None, ge=1)
    video_max_seconds: float | None = Field(default=None, gt=0)
    processing_by: ProcessingBy = "owner"


class WaitingUpload(BaseModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    reason: str | None
    created_at: datetime
    uploaded_by_email: str | None = None
    uploaded_by_name: str | None = None


class HeldVideo(BaseModel):
    id: uuid.UUID
    filename: str
    duration_s: float | None
    reason: str | None
    created_at: datetime
    uploaded_by_email: str | None = None
    uploaded_by_name: str | None = None


class Requests(BaseModel):
    uploads: list[WaitingUpload]
    videos: list[HeldVideo]
