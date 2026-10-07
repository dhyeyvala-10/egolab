"""Pipelines that run on their own: when an upload's video becomes ready, every pipeline marked
`run_on_upload` starts a run on it (trigger `upload`), as its uploader. A pipeline never runs twice on the
same video this way, so re-making a video's derivatives doesn't start it again. A video longer than the
admin's limit is held instead, and starts once they allow it (egolabs.approvals)."""

import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from egolabs import approvals
from egolabs.models import Pipeline, PipelineRun, PipelineStepRun, RunTrigger, Upload, Video, VideoStatus
from egolabs.pipelines import engine
from egolabs.pipelines.schedules import latest_version


def pipelines_for_uploads(db: Session) -> list[Pipeline]:
    return list(
        db.scalars(
            select(Pipeline)
            .where(Pipeline.run_on_upload, Pipeline.archived_at.is_(None))
            .order_by(Pipeline.created_at, Pipeline.id)
        ).all()
    )


def start_for_video(db: Session, video_id: uuid.UUID) -> list[tuple[str, int]]:
    """Start each `run_on_upload` pipeline on a video that just became ready (commits, then sends the jobs).
    Returns (pipeline name, run number) for each run started."""
    video = db.get(Video, video_id)
    if video is None or video.status != VideoStatus.ready:
        return []
    if approvals.hold_if_too_long(db, video):
        db.commit()
        return []
    uploader = (
        db.scalar(select(Upload.created_by).where(Upload.id == video.upload_id)) if video.upload_id else None
    )
    started: list[tuple[str, int]] = []
    for pipeline in pipelines_for_uploads(db):
        already = db.scalar(
            select(
                exists().where(
                    PipelineStepRun.video_id == video_id,
                    PipelineStepRun.run_id == PipelineRun.id,
                    PipelineRun.pipeline_id == pipeline.id,
                )
            )
        )
        version = latest_version(db, pipeline.id)
        if already or version is None:
            continue
        run, to_send = engine.start_run(db, version, [video_id], {"video_ids": [str(video_id)]},
                                        trigger=RunTrigger.upload, user_id=uploader or pipeline.created_by)  # fmt: skip
        started.append((pipeline.name, run.number))
        db.commit()
        engine.send(db, to_send)
    return started
