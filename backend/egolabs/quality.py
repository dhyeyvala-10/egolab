"""
Video quality flags: what the dataset builder can leave out (spec Phase 6). Each is derived from data the
system already has; Phase 7's quality-check steps add their own (blur, low light, occlusion, duplicates) to
the same list.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from egolabs.models import CvRun, CvRunKind, CvRunStatus, Video, VideoStatus

FLAGS: dict[str, str] = {
    "corrupt": "The file failed to decode (ingest).",
    "variable_frame_rate": "Frame timestamps are not evenly spaced (frame index).",
    "hand_tracking_failures": "The latest hand-tracking run lost a hand and found it again under a new track.",
}


# Set by the quality-check steps of a pipeline (egolabs.quality_checks); `refresh` keeps them as they are.
CHECK_FLAGS: dict[str, str] = {
    "blurry": "Most sampled frames are blurry (blur check).",
    "low_light": "Most sampled frames are dark (low-light check).",
    "high_occlusion": "Many finger observations were occluded (occlusion check).",
    "near_duplicate": "Another video has the same footage (near-duplicate check).",
}


def refresh(db: Session, video: Video) -> list[str]:
    """Recompute the flags derived here, keeping any others (e.g. Phase 7 checks) as they are."""
    derived = set()
    if video.status == VideoStatus.corrupt:
        derived.add("corrupt")
    index = (video.derivatives or {}).get("frame_index") or {}
    if int(index.get("runs") or 0) > 1:
        derived.add("variable_frame_rate")
    hand = db.scalar(
        select(CvRun.tracking_failures)
        .where(
            CvRun.video_id == video.id,
            CvRun.kind == CvRunKind.hand_tracking.value,
            CvRun.status == CvRunStatus.succeeded,
        )  # fmt: skip
        .order_by(CvRun.finished_at.desc(), CvRun.id)
        .limit(1)
    )
    if hand:
        derived.add("hand_tracking_failures")
    kept = [f for f in (video.quality_flags or []) if f not in FLAGS]
    video.quality_flags = sorted(derived) + kept
    return video.quality_flags
