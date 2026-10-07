from enum import StrEnum


class Role(StrEnum):
    admin = "admin"  # the owner only (see egolabs.owner)
    annotator = "annotator"
    reviewer = "reviewer"
    viewer = "viewer"
    pending = "pending"  # signed in, but no access until the admin gives them a role


class VideoStatus(StrEnum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    corrupt = "corrupt"


class VideoSource(StrEnum):
    file = "file"  # uploaded directly
    archive_member = "archive_member"  # a video file inside an uploaded ZIP
    image_sequence = "image_sequence"  # a folder of frames inside an uploaded ZIP


class UploadKind(StrEnum):
    video = "video"
    archive = "archive"  # ZIP: videos, image sequences, sidecars
    sidecar = "sidecar"  # JSON/CSV metadata


class UploadStatus(StrEnum):
    awaiting_approval = "awaiting_approval"  # over the admin's size limit; nothing is sent until allowed
    rejected = "rejected"  # the admin turned it down
    uploading = "uploading"  # multipart upload in progress (resumable)
    processing = "processing"  # completed, queued/being ingested
    processed = "processed"
    duplicate = "duplicate"  # exact duplicate of an existing video; linked, not stored twice
    failed = "failed"
    aborted = "aborted"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    retrying = "retrying"


ACTIVE_JOB_STATUSES = (JobStatus.queued, JobStatus.running, JobStatus.retrying)


class LogLevel(StrEnum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"


class AnnotationSource(StrEnum):
    """Principle 4: AI output is always distinguishable from human work."""

    auto = "auto"
    human = "human"
    auto_corrected = "auto_corrected"


class AnnotationType(StrEnum):
    segment = "segment"  # a frame range
    bbox = "bbox"  # a box on the frame range
    keypoint = "keypoint"  # named points on the frame range


class AnnotationCategory(StrEnum):
    """What an annotation is about. CV outputs of a category get their own timeline track."""

    general = "general"
    hand = "hand"
    finger = "finger"
    object = "object"  # object interaction
    movement = "movement"


class RevisionAction(StrEnum):
    created = "created"
    updated = "updated"
    flagged = "flagged"  # marked for review
    unflagged = "unflagged"
    deleted = "deleted"  # soft delete; the row and its history stay
    restored = "restored"
    superseded = "superseded"  # an AI annotation replaced by a human correction (a new annotation)


class AssignmentStatus(StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class CvRunStatus(StrEnum):
    waiting = "waiting"  # on the runs it takes input from (e.g. movement waits on hand tracking)
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class CvRunKind(StrEnum):
    hand_tracking = "hand_tracking"
    object_detection = "object_detection"
    movement = "movement"  # movement classification + hand–object contact


class MovementEventStatus(StrEnum):
    auto_detected = "auto_detected"
    needs_review = "needs_review"  # detected below the review confidence threshold, or flagged
    confirmed = "confirmed"
    rejected = "rejected"
    corrected = "corrected"  # a human correction replaced the prediction (kept as the correction's parent)


class ReviewMethod(StrEnum):
    """How an event's status changed (the review log). Principle 4: rule-based accepts are not human reviews."""

    individual = "individual"  # a person reviewed this event on its own
    bulk = "bulk"  # a person accepted/rejected a filtered set at once (a review batch)
    auto_rule = "auto_rule"  # an auto-accept rule, no person involved
    correction = "correction"  # a person corrected the event (a new event version)
    inspector = "inspector"  # a person edited, flagged, deleted, or restored its segment in the inspector
    undo = "undo"  # a person undid a review batch


class BuildStatus(StrEnum):
    """A dataset version, check, or export being built by a worker job (spec Phase 6)."""

    building = "building"
    ready = "ready"
    failed = "failed"


class ExportFormat(StrEnum):
    coco = "coco"
    jsonl = "jsonl"
    parquet = "parquet"
    webdataset = "webdataset"
    egolabs = "egolabs"  # the native format: manifest + samples + keypoints + provenance


class SplitGroup(StrEnum):
    """What must stay together in one split, so the same scene or person never leaks across splits."""

    session = "session"
    operator = "operator"
    video = "video"
    sample = "sample"  # no grouping


class PipelineRunStatus(StrEnum):
    """A pipeline run (spec Phase 7). `failed` means a step failed and nothing after it can run until it is
    retried; retrying puts the run back to `running`."""

    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class StepStatus(StrEnum):
    """One step of a run, for one video (or once for the whole run), and each attempt at it."""

    pending = "pending"  # waiting for the steps before it
    queued = "queued"
    running = "running"
    retry_wait = "retry_wait"  # failed; an automatic retry is scheduled (`retry_at`)
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"  # not applicable (e.g. a corrupt video), with the reason
    cancelled = "cancelled"


class RunTrigger(StrEnum):
    manual = "manual"
    schedule = "schedule"
    upload = "upload"  # a pipeline with run_on_upload, started when a new video became ready


class ProcessingHold(StrEnum):
    """A video longer than the admin's limit waits for them before anything processes it."""

    held = "held"
    allowed = "allowed"
    rejected = "rejected"
