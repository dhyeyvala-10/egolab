import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, false, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import Role


class User(UUIDPk, CreatedAt, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    # Null for accounts that sign in with Google (the only way people sign in; see `api/auth.py`).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Google's stable account id (the ID token's `sub`), set on the first Google sign-in.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    # New accounts have no access until the owner gives them a role.
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"), default=Role.pending)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Owners (OWNER_EMAIL) are the admins; nobody can change them from the app (egolabs.owner).
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last request the account made (updated at most once a minute): "online now" on the Users page.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignIn(UUIDPk, CreatedAt, Base):
    """One sign-in, with where it came from, so the owner can spot an account used somewhere unexpected."""

    __tablename__ = "sign_ins"
    __table_args__ = (Index("ix_sign_ins_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(16))  # google | password
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class AppSetting(Base):
    """Settings the owner changes in the app (upload limits, who may start processing), one row per key."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
