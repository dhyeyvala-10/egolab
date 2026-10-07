"""
The steps a pipeline is made of (spec Phase 7). Each step type has a config model (validated when a
version is saved, with its defaults written into the version), what it needs before it, and `run`, which the
step's job calls. Model steps reuse the Phase 3–4 job code inline, so a pipeline makes exactly the model runs
the Vision pages make, with the step's job as their job and log.

Per-video steps run once for each video of a run; whole-run steps (dataset build, export) run once, on the
videos that made it through every per-video step before them.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from egolabs.models import CvRun, CvRunKind, CvRunStatus, Video, VideoSource, VideoStatus
from egolabs.models.enums import ExportFormat, SplitGroup

if TYPE_CHECKING:
    from egolabs.worker.runtime import JobContext


class SkipStep(Exception):  # noqa: N818 - control flow, not an error
    """The step doesn't apply to this video (e.g. it's corrupt); the steps after it are skipped too."""


class MissingInput(LookupError):
    """Something the step reads isn't there (a model run, a file). Retrying won't help until it is."""


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class StepEnv:
    ctx: "JobContext"
    step_run_id: uuid.UUID
    run_id: uuid.UUID
    node_id: str
    video_id: uuid.UUID | None
    config: Any
    upstream: dict[str, dict[str, Any]]  # results of the steps before this one, by step type
    video_ids: list[uuid.UUID] = field(default_factory=list)  # whole-run steps: videos that made it through
    user_id: uuid.UUID | None = None

    def session(self) -> Session:
        return self.ctx.session()

    def video(self, db: Session) -> Video:
        assert self.video_id is not None
        video = db.get(Video, self.video_id)
        if video is None:
            raise MissingInput(f"video {self.video_id} not found")
        return video

    def run_for(self, db: Session, kind: CvRunKind, *, optional: bool = False) -> CvRun | None:
        """The model run of `kind` a step before this one made, else the video's latest successful one."""
        up = self.upstream.get(kind.value, {})
        if up.get("cv_run_id"):
            run = db.get(CvRun, uuid.UUID(up["cv_run_id"]))
            if run is not None:
                return run
        from egolabs.cv.runs import latest_succeeded

        assert self.video_id is not None
        run = latest_succeeded(db, self.video_id, kind.value)
        if run is None and not optional:
            raise MissingInput(
                f"no successful {kind.value.replace('_', ' ')} run for this video; add that step before this one"
            )
        if run is not None:
            self.ctx.info(
                f"Using the video's latest {kind.value.replace('_', ' ')} run", cv_run_id=str(run.id)
            )
        return run


@dataclass(frozen=True)
class StepType:
    key: str
    label: str
    category: str
    per_video: bool
    description: str
    config: type[BaseModel]
    run: Callable[[StepEnv], dict[str, Any]]
    requires: tuple[str, ...] = ()  # step types that must come before it
    uses: tuple[str, ...] = ()  # read from a step before it if there is one, else the latest successful run
    check: Callable[[Any], str | None] = field(default=lambda _c: None)


def _not_corrupt(video: Video) -> None:
    if video.status == VideoStatus.corrupt:
        raise SkipStep(f"the video is corrupt: {video.error or 'it failed to decode'}")


# --- ingest --------------------------------------------------------------------------------------------


class IngestConfig(_Config):
    verify_checksum: bool = Field(
        False, description="Download the raw file and compare its SHA-256 with the one recorded at ingest"
    )


def run_ingest(env: StepEnv) -> dict[str, Any]:
    from egolabs import storage
    from egolabs.config import get_settings

    bucket = get_settings().s3_bucket_raw
    with env.session() as db:
        video = env.video(db)
        _not_corrupt(video)
        key, kind, size, sha = video.storage_key, video.source_kind, video.size_bytes, video.sha256
    if kind == VideoSource.image_sequence:
        frames = storage.list_keys(bucket, key)
        if not frames:
            raise MissingInput(f"the raw frames under {key} are missing from storage")
        env.ctx.info("Raw frames present", key=key, frames=len(frames))
        return {"storage_key": key, "frames": len(frames), "checksum_verified": False}
    stored = storage.object_size(bucket, key)
    if stored is None:
        raise MissingInput(f"the raw file {key} is missing from storage")
    if stored != size:
        raise ValueError(f"the raw file is {stored} bytes in storage but {size} bytes were ingested")
    env.ctx.info("Raw file present", key=key, size_bytes=stored)
    verified = False
    if env.config.verify_checksum:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(dir=get_settings().work_dir, prefix="egolabs-check-") as tmp:
            digest, _ = storage.download_and_hash(bucket, key, Path(tmp) / "raw")
        if digest != sha:
            raise ValueError(f"the raw file's SHA-256 is {digest}, not {sha} as ingested")
        env.ctx.info("Checksum matches", sha256=digest)
        verified = True
    return {"storage_key": key, "size_bytes": stored, "checksum_verified": verified}


# --- frames --------------------------------------------------------------------------------------------


class ExtractFramesConfig(_Config):
    rebuild: bool = Field(False, description="Rebuild the proxy and frame index even if the video has them")


def run_extract_frames(env: StepEnv) -> dict[str, Any]:
    with env.session() as db:
        video = env.video(db)
        _not_corrupt(video)
        index = (video.derivatives or {}).get("frame_index")
        have = bool(video.proxy_key and index)
        frames = (video.derivatives or {}).get("proxy", {}).get("frame_count") or video.frame_count
    if have and not env.config.rebuild:
        env.ctx.info("Frames already extracted: frame-exact proxy and frame index", proxy_frames=frames,
                     timestamp_runs=index.get("runs"))  # fmt: skip
        return {"rebuilt": False, "frames": frames, "frame_index": index}
    from egolabs.ingest.pipeline import ingest_derivatives

    out = ingest_derivatives(env.ctx, {"video_id": str(env.video_id)})
    return {"rebuilt": True, "frames": out.get("proxy_frames"), "frame_index": out.get("frame_index")}


# --- models --------------------------------------------------------------------------------------------


class ModelConfig(_Config):
    adapter: str | None = Field(
        None, description="An adapter name or package.module:Class; empty uses the configured adapter"
    )
    adapter_config: dict[str, Any] = Field(default_factory=dict, description="The adapter's JSON config")
    stride: int = Field(1, ge=1, le=30, description="Process every Nth frame")
    reuse: bool = Field(
        False, description="Use the video's latest successful run with the same model and settings, if any"
    )


def _check_adapter(kind: str) -> Callable[[Any], str | None]:
    def check(config: ModelConfig) -> str | None:
        if not config.adapter:
            return None
        from egolabs.cv import registry
        from egolabs.cv.adapters.base import AdapterError

        try:
            cls = registry.resolve(config.adapter, kind)
        except AdapterError as exc:
            return str(exc)
        if registry.is_stub(cls):
            return f"{config.adapter} is a documented stub, not a working adapter"
        return None

    return check


def _handler(kind: CvRunKind) -> Callable[..., dict[str, Any]]:
    if kind == CvRunKind.hand_tracking:
        from egolabs.cv.pipeline import hand_tracking

        return hand_tracking
    if kind == CvRunKind.object_detection:
        from egolabs.cv.objects import object_detection

        return object_detection
    from egolabs.cv.movement.job import movement

    return movement


def _model_step(kind: CvRunKind) -> Callable[[StepEnv], dict[str, Any]]:
    def run(env: StepEnv) -> dict[str, Any]:
        from egolabs.cv import registry

        cfg: ModelConfig = env.config
        name, conf = (
            (cfg.adapter, dict(cfg.adapter_config)) if cfg.adapter else registry.configured(kind.value)
        )
        stride = 1 if kind == CvRunKind.movement else cfg.stride
        with env.session() as db:
            video = env.video(db)
            _not_corrupt(video)
            inputs: dict[str, str] = {}
            if kind == CvRunKind.movement:
                hand = env.run_for(db, CvRunKind.hand_tracking)
                assert hand is not None
                inputs[CvRunKind.hand_tracking.value] = str(hand.id)
                obj = env.run_for(db, CvRunKind.object_detection, optional=True)
                if obj is not None:
                    inputs[CvRunKind.object_detection.value] = str(obj.id)
            if cfg.reuse:
                prior = db.scalar(
                    select(CvRun)
                    .where(
                        CvRun.video_id == video.id,
                        CvRun.kind == kind.value,
                        CvRun.status == CvRunStatus.succeeded,
                        CvRun.adapter == name,
                        CvRun.config == conf,
                        CvRun.stride == stride,
                        CvRun.inputs == inputs,
                    )  # fmt: skip
                    .order_by(CvRun.finished_at.desc(), CvRun.id)
                    .limit(1)
                )
                if prior is not None:
                    env.ctx.info(
                        "Reusing an earlier run with the same model and settings", cv_run_id=str(prior.id)
                    )
                    return {"cv_run_id": str(prior.id), "reused": True, "tracks": prior.tracks,
                            "detections": prior.detections}  # fmt: skip
            run = CvRun(video_id=video.id, kind=kind.value, adapter=name, config=conf, stride=stride,
                        created_by=env.user_id, frames_total=video.frame_count, status=CvRunStatus.queued,
                        job_id=env.ctx.job_id, inputs=inputs)  # fmt: skip
            db.add(run)
            db.commit()
            run_id = run.id
        stats = _handler(kind)(env.ctx, {"run_id": str(run_id)}) or {}
        return {"cv_run_id": str(run_id), "reused": False, **stats}

    return run


# --- fingers -------------------------------------------------------------------------------------------


class FingerConfig(_Config):
    min_visibility: float = Field(
        0.5, ge=0, le=1, description="Warn about fingers whose mean visibility is below this"
    )


def run_fingers(env: StepEnv) -> dict[str, Any]:
    with env.session() as db:
        video = env.video(db)
        _not_corrupt(video)
        hand = env.run_for(db, CvRunKind.hand_tracking)
        assert hand is not None
        stats = dict((hand.stats or {}).get("fingers") or {})
        rows = dict((hand.output or {}).get("rows") or {})
        hand_id = hand.id
    hands, fingers = int(rows.get("hands", 0)), int(rows.get("fingers", 0))
    if fingers != hands * 5:
        raise ValueError(
            f"hand run {hand_id} has {hands} hand rows but {fingers} finger rows (expected 5 per hand)"
        )
    low = sorted(
        f
        for f, s in stats.items()
        if s.get("visibility") is not None and s["visibility"] < env.config.min_visibility
    )
    for f in low:
        env.ctx.warning(f"{f} is poorly visible", finger=f, visibility=stats[f]["visibility"],
                        threshold=env.config.min_visibility)  # fmt: skip
    env.ctx.info("Finger features checked", hand_rows=hands, finger_rows=fingers,
                 fingers={f: s.get("visibility") for f, s in stats.items()})  # fmt: skip
    return {"hand_run_id": str(hand_id), "hand_rows": hands, "finger_rows": fingers, "fingers": stats,
            "low_visibility": low}  # fmt: skip


# --- quality checks ------------------------------------------------------------------------------------


class BlurConfig(_Config):
    sample_fps: float = Field(1.0, gt=0, le=10, description="Frames sampled per second")
    threshold: float = Field(
        60.0,
        gt=0,
        description="Variance of the Laplacian (frames scaled to 640 px wide) below which a frame is blurry",
    )
    max_fraction: float = Field(
        0.5, ge=0, le=1, description="Flag the video when more than this share is blurry"
    )


class LowLightConfig(_Config):
    sample_fps: float = Field(1.0, gt=0, le=10)
    luma_threshold: float = Field(
        50.0, ge=0, le=255, description="Mean brightness (0–255) below which a frame is dark"
    )
    max_fraction: float = Field(
        0.5, ge=0, le=1, description="Flag the video when more than this share is dark"
    )


class OcclusionConfig(_Config):
    max_rate: float = Field(
        0.5,
        ge=0,
        le=1,
        description="Flag the video when more than this share of finger observations is occluded",
    )


class DuplicatesConfig(_Config):
    sample_fps: float = Field(1.0, gt=0, le=10)
    max_distance: int = Field(
        6, ge=0, le=7, description="Bits two frame hashes may differ by and still match"
    )
    min_overlap: float = Field(
        0.6,
        gt=0,
        le=1,
        description="Share of sampled frames that must match another video's to call it a near-duplicate",
    )


def _quality(check: str) -> Callable[[StepEnv], dict[str, Any]]:
    def run(env: StepEnv) -> dict[str, Any]:
        from egolabs import quality_checks

        hand_run_id = None
        with env.session() as db:
            video = env.video(db)
            _not_corrupt(video)
            if check == "occlusion":
                hand = env.run_for(db, CvRunKind.hand_tracking)
                assert hand is not None
                hand_run_id = hand.id
        return quality_checks.run(
            env.ctx, check, env.video_id, env.config.model_dump(), hand_run_id=hand_run_id
        )  # type: ignore[arg-type]

    return run


# --- annotated video -----------------------------------------------------------------------------------


class RenderConfig(_Config):
    max_side: int = Field(720, ge=240, le=2160, description="Longest side of the rendered video, in pixels")
    codec: Literal["h264", "vp9"] = Field("h264", description="h264 (.mp4) plays everywhere; vp9 (.webm)")
    skeleton: bool = True
    objects: bool = True
    events: bool = True


def run_render(env: StepEnv) -> dict[str, Any]:
    from egolabs import render

    with env.session() as db:
        video = env.video(db)
        _not_corrupt(video)
        hand = env.run_for(db, CvRunKind.hand_tracking, optional=True)
        obj = env.run_for(db, CvRunKind.object_detection, optional=True)
        mov = env.run_for(db, CvRunKind.movement, optional=True)
        if hand is None and obj is None and mov is None:
            raise MissingInput("nothing to draw: the video has no hand, object, or movement run")
    return render.render(env.ctx, env.video_id, hand_run_id=hand.id if hand else None,  # type: ignore[arg-type]
                         object_run_id=obj.id if obj else None, movement_run_id=mov.id if mov else None,
                         options=env.config.model_dump(), user_id=env.user_id)  # fmt: skip


# --- dataset build and export --------------------------------------------------------------------------


class SplitConfig(_Config):
    train: float = Field(0.8, ge=0, le=1)
    val: float = Field(0.1, ge=0, le=1)
    test: float = Field(0.1, ge=0, le=1)
    group_by: SplitGroup = SplitGroup.session
    seed: int = Field(0, ge=0, le=2**31 - 1)


class DatasetBuildConfig(_Config):
    dataset: str = Field(
        ..., min_length=1, max_length=200, description="Dataset name (created if it doesn't exist)"
    )
    statuses: list[Literal["auto_detected", "needs_review", "confirmed", "rejected"]] = Field(
        default_factory=lambda: ["confirmed"], min_length=1, description="Review statuses to include"
    )
    classes: list[str] = Field(default_factory=list, description="Movement classes to include (empty: all)")
    human_verified_only: bool = False
    min_confidence: float | None = Field(None, ge=0, le=1)
    exclude_quality_flags: list[str] = Field(
        default_factory=list, description="Leave out videos with these flags"
    )
    split: SplitConfig = Field(default_factory=SplitConfig)
    note: str | None = Field(None, max_length=2000)


def _check_split(config: DatasetBuildConfig) -> str | None:
    s = config.split
    return None if abs(s.train + s.val + s.test - 1.0) < 1e-6 else "train + val + test must add up to 1"


def run_dataset_build(env: StepEnv) -> dict[str, Any]:
    from egolabs.datasets import build
    from egolabs.models import Dataset
    from egolabs.schemas.datasets import DatasetFilters, DatasetSpec, SplitSpec

    cfg: DatasetBuildConfig = env.config
    if not env.video_ids:
        raise SkipStep("no video made it through the steps before this one")
    spec = DatasetSpec(
        filters=DatasetFilters(video_ids=env.video_ids, statuses=cfg.statuses, classes=cfg.classes,
                               human_verified_only=cfg.human_verified_only, min_confidence=cfg.min_confidence,
                               exclude_quality_flags=cfg.exclude_quality_flags),
        split=SplitSpec(**cfg.split.model_dump()),
    )  # fmt: skip
    with env.session() as db:
        dataset = db.scalar(select(Dataset).where(Dataset.name == cfg.dataset))
        if dataset is None:
            dataset = Dataset(name=cfg.dataset, description="Created by a pipeline", created_by=env.user_id)
            db.add(dataset)
            db.commit()
            env.ctx.info("Created dataset", dataset=cfg.dataset)
        version = build.create_version(db, dataset, spec, env.user_id,
                                       cfg.note or f"Built by pipeline run {env.run_id}")  # fmt: skip
        if not version.inputs["runs"]:
            db.rollback()
            raise MissingInput("none of the run's videos has a movement classification run to build from")
        version.job_id = env.ctx.job_id
        db.commit()
        version_id, number, dataset_id = version.id, version.number, dataset.id
    out = build.build_version(env.ctx, {"version_id": str(version_id)})
    return {"dataset_id": str(dataset_id), "dataset": cfg.dataset, "dataset_version_id": str(version_id),
            "number": number, "samples": out["samples"], "content_hash": out["content_hash"]}  # fmt: skip


class ExportConfig(_Config):
    formats: list[ExportFormat] = Field(default_factory=lambda: [ExportFormat.egolabs], min_length=1)


def run_export(env: StepEnv) -> dict[str, Any]:
    from egolabs.datasets.export import export_version
    from egolabs.models import DatasetExport, DatasetVersion

    version_id = env.upstream.get("dataset_build", {}).get("dataset_version_id")
    if not version_id:
        raise MissingInput("the dataset build step before this one didn't produce a version")
    exports = []
    for fmt in dict.fromkeys(env.config.formats):
        with env.session() as db:
            if db.get(DatasetVersion, uuid.UUID(version_id)) is None:
                raise MissingInput(f"dataset version {version_id} not found")
            ex = DatasetExport(version_id=uuid.UUID(version_id), format=fmt, created_by=env.user_id,
                               job_id=env.ctx.job_id)  # fmt: skip
            db.add(ex)
            db.commit()
            ex_id = ex.id
        out = export_version(env.ctx, {"export_id": str(ex_id)})
        exports.append({"id": str(ex_id), "format": ExportFormat(fmt).value, "size_bytes": out["size_bytes"],
                        "sha256": out["sha256"]})  # fmt: skip
    return {"dataset_version_id": version_id, "exports": exports}


STEPS: dict[str, StepType] = {
    s.key: s
    for s in [
        StepType("ingest", "Ingest check", "Ingest", True,
                 "Confirms the raw file is in storage as ingested (optionally re-checking its SHA-256). Corrupt "
                 "videos are skipped, and so is everything after them.", IngestConfig, run_ingest),
        StepType("extract_frames", "Extract frames", "Ingest", True,
                 "Makes sure the video has its frame-exact proxy and frame index (builds them if missing).",
                 ExtractFramesConfig, run_extract_frames),
        StepType("hand_tracking", "Hand tracking", "Tracking", True,
                 "Runs the hand-tracking model: keypoints, tracks, and per-finger features, as a new model run.",
                 ModelConfig, _model_step(CvRunKind.hand_tracking), check=_check_adapter("hand_tracking")),
        StepType("finger_tracking", "Finger tracking", "Tracking", True,
                 "Checks the hand run's per-finger features (five per hand) and reports each finger's visibility, "
                 "occlusion, and speed.", FingerConfig, run_fingers, requires=("hand_tracking",)),
        StepType("object_detection", "Object detection", "Tracking", True,
                 "Runs the object-detection model and tracks each object, as a new model run.",
                 ModelConfig, _model_step(CvRunKind.object_detection), check=_check_adapter("object_detection")),
        StepType("movement", "Movement classification", "Movement", True,
                 "Classifies movements from the hand run (and objects, if any), putting events on the timeline.",
                 ModelConfig, _model_step(CvRunKind.movement), uses=("hand_tracking", "object_detection"),
                 check=_check_adapter("movement")),
        StepType("quality_blur", "Blur check", "Quality", True,
                 "Measures sharpness (variance of the Laplacian) on sampled frames; flags the video `blurry`.",
                 BlurConfig, _quality("blur")),
        StepType("quality_low_light", "Low-light check", "Quality", True,
                 "Measures brightness on sampled frames; flags the video `low_light`.", LowLightConfig,
                 _quality("low_light")),
        StepType("quality_occlusion", "Occlusion check", "Quality", True,
                 "Share of finger observations the hand run marked occluded; flags the video `high_occlusion`.",
                 OcclusionConfig, _quality("occlusion"), uses=("hand_tracking",)),
        StepType("quality_duplicates", "Near-duplicate check", "Quality", True,
                 "Hashes sampled frames and looks for other videos with the same footage; flags `near_duplicate`.",
                 DuplicatesConfig, _quality("duplicates")),
        StepType("render_video", "Annotated video", "Output", True,
                 "Renders the video with hand skeletons, object boxes, and movement events drawn on, to download.",
                 RenderConfig, run_render, uses=("hand_tracking", "object_detection", "movement")),
        StepType("dataset_build", "Dataset build", "Dataset", False,
                 "Builds a new version of a dataset from the run's videos, with these filters and split.",
                 DatasetBuildConfig, run_dataset_build, check=_check_split),
        StepType("export", "Export", "Dataset", False,
                 "Exports the version the dataset build made, in each chosen format.", ExportConfig, run_export,
                 requires=("dataset_build",)),
    ]
}  # fmt: skip
