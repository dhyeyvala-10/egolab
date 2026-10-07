"""The database itself enforces the product principles, not only the API."""

import pytest
from sqlalchemy.exc import IntegrityError

from egolabs.models import (
    Annotation,
    AnnotationSource,
    AnnotationType,
    CaptureSession,
    Frame,
    LineageEdge,
    ModelVersion,
    User,
    Video,
)


@pytest.fixture
def video(db) -> Video:
    v = Video(original_filename="a.mp4", storage_key="raw/a.mp4", sha256="a" * 64, size_bytes=10)
    db.add(v)
    db.commit()
    return v


@pytest.fixture
def model(db) -> ModelVersion:
    m = ModelVersion(
        name="mediapipe-hands", version="0.10.14", kind="hand_tracking", adapter="egolabs.cv.MediaPipe"
    )
    db.add(m)
    db.commit()
    return m


def _ann(**kw) -> Annotation:
    base = dict(type=AnnotationType.segment, label="grasp", frame_start=10, frame_end=20)
    return Annotation(**(base | kw))


def test_auto_annotation_needs_confidence_and_model_version(db, video, model):
    db.add(_ann(video_id=video.id, source=AnnotationSource.auto, confidence=0.9))
    with pytest.raises(IntegrityError, match="auto_has_confidence_and_model"):
        db.commit()
    db.rollback()
    db.add(_ann(video_id=video.id, source=AnnotationSource.auto, model_version_id=model.id))
    with pytest.raises(IntegrityError, match="auto_has_confidence_and_model"):
        db.commit()
    db.rollback()
    db.add(_ann(video_id=video.id, source=AnnotationSource.auto, confidence=0.9, model_version_id=model.id))
    db.commit()


def test_correction_keeps_the_original_as_parent(db, video, model):
    user = User(email="a@example.com", password_hash="x")
    original = _ann(
        video_id=video.id, source=AnnotationSource.auto, confidence=0.4, model_version_id=model.id
    )
    db.add_all([user, original])
    db.commit()

    db.add(_ann(video_id=video.id, source=AnnotationSource.auto_corrected, created_by=user.id))
    with pytest.raises(IntegrityError, match="correction_has_parent"):
        db.commit()
    db.rollback()

    corrected = _ann(
        video_id=video.id,
        source=AnnotationSource.auto_corrected,
        created_by=user.id,
        parent_annotation_id=original.id,
        frame_end=18,
    )
    db.add(corrected)
    db.commit()
    db.delete(original)
    with pytest.raises(IntegrityError):  # the original prediction cannot be removed from under its correction
        db.commit()


def test_human_annotation_needs_an_author(db, video):
    db.add(_ann(video_id=video.id, source=AnnotationSource.human))
    with pytest.raises(IntegrityError, match="human_has_author"):
        db.commit()


def test_confidence_and_frame_range_are_validated(db, video, model):
    db.add(_ann(video_id=video.id, source=AnnotationSource.auto, confidence=1.5, model_version_id=model.id))
    with pytest.raises(IntegrityError, match="confidence_range"):
        db.commit()
    db.rollback()
    db.add(
        _ann(
            video_id=video.id,
            source=AnnotationSource.auto,
            confidence=0.5,
            model_version_id=model.id,
            frame_start=20,
            frame_end=10,
        )
    )
    with pytest.raises(IntegrityError, match="frame_range"):
        db.commit()


def test_session_names_follow_the_convention(db):
    db.add(CaptureSession(name="SESSION_2026_09_23_001"))
    db.commit()
    db.add(CaptureSession(name="kitchen-take-2"))
    with pytest.raises(IntegrityError, match="name_format"):
        db.commit()


def test_videos_are_unique_by_checksum(db, video):
    db.add(
        Video(original_filename="copy.mp4", storage_key="raw/copy.mp4", sha256=video.sha256, size_bytes=10)
    )
    with pytest.raises(IntegrityError, match="uq_videos_sha256"):
        db.commit()


def test_frames_are_indexed_once_per_video(db, video):
    db.add(Frame(video_id=video.id, frame_index=42))
    db.commit()
    db.add(Frame(video_id=video.id, frame_index=42))
    with pytest.raises(IntegrityError, match="uq_frames_video_id_frame_index"):
        db.commit()


def test_lineage_edges_reject_self_links(db, video):
    db.add(
        LineageEdge(
            parent_type="video",
            parent_id=video.id,
            child_type="video",
            child_id=video.id,
            relation="derived_from",
        )
    )
    with pytest.raises(IntegrityError, match="no_self_edge"):
        db.commit()
