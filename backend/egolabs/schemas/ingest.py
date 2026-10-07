import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from egolabs.models.enums import UploadKind, UploadStatus
from egolabs.schemas import ApiModel


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0)
    content_type: str | None = Field(default=None, max_length=200)
    session_id: uuid.UUID | None = None
    sequence_fps: float | None = Field(
        default=None, gt=0, le=10_000, description="Frame rate of image sequences inside a ZIP (user input)"
    )


class UploadRead(ApiModel):
    id: uuid.UUID
    filename: str
    content_type: str | None
    size_bytes: int
    kind: UploadKind
    status: UploadStatus
    part_size: int
    session_id: uuid.UUID | None
    sequence_fps: float | None
    video_id: uuid.UUID | None
    job_id: uuid.UUID | None
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    created_by: uuid.UUID | None
    approval_reason: str | None = Field(description="Why it waits for the admin (over their size limit)")
    reviewed_at: datetime | None
    # Filled in lists and details: who sent it (the admin sees everyone's; others only see their own), and while
    # it's uploading, how much has arrived and when the last piece did (a paused upload stops moving).
    uploaded_by_email: str | None = None
    uploaded_by_name: str | None = None
    received_bytes: int | None = None
    last_data_at: datetime | None = None

    @computed_field
    @property
    def part_count(self) -> int:
        return max(1, -(-self.size_bytes // self.part_size))


class UploadedPart(BaseModel):
    part_number: int
    etag: str
    size: int
    last_modified: datetime | None = None


class UploadReview(BaseModel):
    reason: str | None = Field(
        default=None, max_length=500, description="Told to the uploader when rejecting"
    )


class UploadDetail(UploadRead):
    uploaded_parts: list[UploadedPart] = Field(
        default_factory=list, description="Parts already in storage (while uploading), for resuming"
    )


class PartUrlRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=100)


class PartUrl(BaseModel):
    part_number: int
    url: str


class PartUrlResponse(BaseModel):
    urls: list[PartUrl]
    expires_in: int


class CompletedPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=200)


class UploadComplete(BaseModel):
    parts: list[CompletedPart] = Field(min_length=1, max_length=10_000)
