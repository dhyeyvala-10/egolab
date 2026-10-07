"""Which videos a run processes: a selector (videos, sessions, datasets, or everything), resolved and pinned
when the run starts. Videos still being ingested are left out; a schedule picks them up next time."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.orm import Session

from egolabs.config import get_settings
from egolabs.models import (
    PipelineRun,
    PipelineRunStatus,
    PipelineStepRun,
    ProcessingHold,
    Video,
    VideoStatus,
    dataset_sessions,
)


class RunInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    session_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    dataset_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=100, description="The datasets' sessions"
    )
    all_videos: bool = Field(False, description="Every ingested video")

    def empty(self) -> bool:
        return not (self.video_ids or self.session_ids or self.dataset_ids or self.all_videos)


class InputError(ValueError):
    pass


def processable() -> ColumnElement[bool]:
    """Videos nothing is holding back: not waiting for, or turned down by, the admin."""
    return Video.processing_hold.is_(None) | (Video.processing_hold == ProcessingHold.allowed)


def resolve(db: Session, sel: RunInputs, *, only_new_for: uuid.UUID | None = None) -> list[uuid.UUID]:
    """The ingested (ready or corrupt) videos the selector picks, oldest first. `only_new_for` leaves out
    videos that pipeline already processed in a run that succeeded. Videos held for the admin (longer than
    their limit, and not allowed) are left out."""
    if sel.empty():
        raise InputError("Choose videos, sessions, or datasets to run on (or all videos)")
    q = select(Video.id).where(Video.status.in_((VideoStatus.ready, VideoStatus.corrupt)), processable())
    if not sel.all_videos:
        conds = []
        if sel.video_ids:
            conds.append(Video.id.in_(sel.video_ids))
        if sel.session_ids:
            conds.append(Video.session_id.in_(sel.session_ids))
        if sel.dataset_ids:
            conds.append(Video.session_id.in_(
                select(dataset_sessions.c.session_id).where(dataset_sessions.c.dataset_id.in_(sel.dataset_ids))))  # fmt: skip
        q = q.where(or_(*conds))
    if only_new_for is not None:
        done = (
            select(PipelineStepRun.id)
            .join(PipelineRun, PipelineRun.id == PipelineStepRun.run_id)
            .where(
                PipelineRun.pipeline_id == only_new_for,
                PipelineRun.status == PipelineRunStatus.succeeded,
                PipelineStepRun.video_id == Video.id,
            )  # fmt: skip
        )
        q = q.where(~exists(done))
    limit = get_settings().pipeline_max_videos
    ids = list(db.scalars(q.order_by(Video.created_at, Video.id).limit(limit + 1)).all())
    if len(ids) > limit:
        raise InputError(f"More than {limit} videos match; narrow the selection (PIPELINE_MAX_VIDEOS)")
    return ids


def describe(sel: dict[str, Any]) -> str:
    parts = []
    if sel.get("all_videos"):
        return "All videos"
    for key, word in (("video_ids", "video"), ("session_ids", "session"), ("dataset_ids", "dataset")):
        n = len(sel.get(key) or [])
        if n:
            parts.append(f"{n} {word}{'s' if n != 1 else ''}")
    return ", ".join(parts) or "Nothing"
