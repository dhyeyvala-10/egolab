"""Pydantic API schemas. The web app's TypeScript types are generated from these (see `egolabs.openapi`)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from egolabs.models.enums import JobStatus, LogLevel, Role

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# --- auth / users ---------------------------------------------------------------------------------

Password = Annotated[str, StringConstraints(min_length=8, max_length=256)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(max_length=256)]


class GoogleConfig(BaseModel):
    enabled: bool = Field(description="Whether Google sign-in is set up (client id and secret)")
    client_id: str | None
    authorize_url: str


class GoogleSignIn(BaseModel):
    code: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    redirect_uri: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    code_verifier: Annotated[str, StringConstraints(min_length=43, max_length=128)] = Field(
        description="The PKCE verifier whose S256 challenge went to Google"
    )


class UserRead(ApiModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: Role = Field(description="`pending`: signed in, waiting for the admin to give access")
    is_active: bool
    is_owner: bool = Field(description="The owner is the only admin, and nobody can change them")
    created_at: datetime
    last_sign_in_at: datetime | None
    last_seen_at: datetime | None


# Roles the owner can give. Admin is the owner's alone.
GrantableRole = Literal["annotator", "reviewer", "viewer", "pending"]


class UserUpdate(BaseModel):
    role: GrantableRole | None = None
    is_active: bool | None = None


class SignInRead(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    user_name: str | None
    method: str
    ip: str | None
    user_agent: str | None
    created_at: datetime


class AdminActivity(ApiModel):
    """Everything someone did (an activity event), with who did it."""

    id: int
    type: str
    message: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_email: str | None
    actor_name: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Seconds until the token expires")
    user: UserRead


# --- overview -------------------------------------------------------------------------------------


class JobSummary(ApiModel):
    id: uuid.UUID
    type: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class ActivityEvent(ApiModel):
    id: int
    type: str
    message: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    created_at: datetime


class OverviewCounts(BaseModel):
    datasets: int
    sessions: int
    videos: int
    jobs_active: int


class OverviewResponse(BaseModel):
    counts: OverviewCounts
    recent_jobs: list[JobSummary]
    recent_events: list[ActivityEvent]


# --- health ---------------------------------------------------------------------------------------

CheckStatus = Literal["ok", "error"]


class HealthCheck(BaseModel):
    status: CheckStatus
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    checks: dict[str, HealthCheck]


# --- jobs -----------------------------------------------------------------------------------------


class JobRead(JobSummary):
    payload: dict[str, Any]
    result: dict[str, Any] | None
    attempts: int
    parent_job_id: uuid.UUID | None


class JobLogRead(ApiModel):
    id: int
    ts: datetime
    level: LogLevel
    message: str
    data: dict[str, Any]


class JobLogPage(BaseModel):
    """Cursor page: pass `next_after_id` as `after_id` to continue."""

    items: list[JobLogRead]
    next_after_id: int | None
