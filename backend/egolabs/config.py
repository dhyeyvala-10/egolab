from functools import lru_cache
from typing import Any, Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"


class Settings(BaseSettings):
    """Runtime configuration, read from the environment or `.env` (never hardcoded)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://egolabs:egolabs@localhost:5432/egolabs"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    # Address browsers use to reach storage. Upload URLs are signed for it (defaults to s3_endpoint_url).
    s3_public_endpoint_url: str | None = None
    s3_access_key: str = "egolabs"
    s3_secret_key: SecretStr = SecretStr("egolabs-dev-secret")
    s3_bucket_raw: str = "egolabs-raw"
    s3_bucket_derived: str = "egolabs-derived"
    s3_region: str = "us-east-1"

    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 12

    # Sign-in is with Google (OpenID Connect, authorization code flow). Create an OAuth client of type
    # "Web application" in Google Cloud Console and add `<web address>/auth/google/callback` as an
    # authorised redirect URI. Without these two, the login page says sign-in isn't set up.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_token_url: str = "https://oauth2.googleapis.com/token"
    google_jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs"
    google_issuers: list[str] = ["https://accounts.google.com", "accounts.google.com"]
    # Email and password sign-in (POST /auth/register, /auth/login) is off: the web app signs in with
    # Google only. Turn it on for scripts, the seed data, and the smoke test, never for people.
    password_login: bool = False
    # The owners: the admins, whom nobody can change from the app. One email, or several separated by commas.
    # Everyone else starts with no access until an owner gives them a role. Without it (local development,
    # tests), the first account to sign in is the only owner.
    owner_email: str | None = None

    # Ingestion
    upload_part_size_bytes: int = 16 * 1024 * 1024
    max_upload_bytes: int = 200 * 1024**3
    max_archive_uncompressed_bytes: int = 200 * 1024**3
    work_dir: str | None = None  # scratch space for the worker; defaults to the system temp dir
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    # Inspector proxy codec. H.264 plays in every mainstream browser; VP9 is for browsers built
    # without H.264 (e.g. open-source Chromium, which the browser tests use).
    proxy_codec: Literal["h264", "vp9"] = "h264"

    # Computer vision (spec Phase 3). Swap the hand model by changing these, not code (principle 10).
    hand_tracking_adapter: str = "mediapipe-hands"
    hand_tracking_config: dict[str, Any] = {}
    # Phase 4: object detection and movement classification follow the same pattern.
    object_detection_adapter: str = "mediapipe-objects"
    object_detection_config: dict[str, Any] = {}
    movement_classifier_adapter: str = "rules"
    movement_classifier_config: dict[str, Any] = {}
    # Events below this confidence start as needs_review (and are flagged on the timeline).
    movement_review_confidence: float = 0.6
    # Phase 5 active-learning queue: an item's priority is the weighted sum of how unsure the model was
    # (1 − confidence), how much model versions disagree on it, and how rare its class is.
    review_priority_weights: dict[str, float] = {"confidence": 0.5, "disagreement": 0.3, "rarity": 0.2}
    # Most events one bulk accept/reject may change (narrow the filters for more).
    review_bulk_max: int = 20000
    # Phase 6: the dataset builder's live preview stops counting here (building a version has no limit).
    dataset_preview_max: int = 100000
    # Shard size for WebDataset exports.
    export_shard_samples: int = 1000
    # Phase 7 pipelines: most videos one run may take, the first automatic retry's delay (doubling after),
    # and how long a running job may go without a heartbeat before the scheduler treats its worker as lost.
    pipeline_max_videos: int = 5000
    pipeline_retry_backoff_s: int = 30
    job_heartbeat_s: int = 15
    job_stale_after_s: int = 300
    # What POST /cv/runs does when it isn't told: hand tracking, then object detection, then movement
    # classification on their output (so events reach the timeline without another step).
    cv_default_kinds: list[str] = ["hand_tracking", "object_detection", "movement"]
    model_cache_dir: str | None = (
        None  # where pinned model files are cached (default ~/.cache/egolabs/models)
    )
    cv_max_frame_side: int = (
        1280  # frames are downscaled to this before inference (coordinates are normalised)
    )

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"
    environment: str = "development"

    @model_validator(mode="after")
    def _require_real_secrets(self) -> "Settings":
        if self.environment != "development":
            secret = self.jwt_secret.get_secret_value()
            if secret == DEV_JWT_SECRET or len(secret) < 32:
                raise ValueError("JWT_SECRET must be set to a random value of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
