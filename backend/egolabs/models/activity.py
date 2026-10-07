import uuid
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from egolabs.models.base import Base, CreatedAt, UUIDPk


class Event(CreatedAt, Base):
    """Activity stream entry ("Session uploaded", "Dataset v14 created", …)."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_created_at", "created_at"),
        Index("ix_events_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(100), index=True)  # dotted, e.g. user.registered
    message: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class LineageEdge(UUIDPk, CreatedAt, Base):
    """
    Generic parent → child link between any two entities (principles 1 and 3), e.g.
    frame → annotation, annotation → annotation (correction), job → dataset version.
    """

    __tablename__ = "lineage_edges"
    __table_args__ = (
        UniqueConstraint("parent_type", "parent_id", "child_type", "child_id", "relation"),
        CheckConstraint("NOT (parent_type = child_type AND parent_id = child_id)", name="no_self_edge"),
        Index("ix_lineage_edges_child", "child_type", "child_id"),
        Index("ix_lineage_edges_parent", "parent_type", "parent_id"),
    )

    parent_type: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    child_type: Mapped[str] = mapped_column(String(64))
    child_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    relation: Mapped[str] = mapped_column(String(64))  # derived_from, corrected_from, produced_by, …
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
