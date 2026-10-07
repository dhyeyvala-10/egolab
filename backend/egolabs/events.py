import uuid
from typing import Any

from sqlalchemy.orm import Session

from egolabs.models import Event


def record_event(
    db: Session,
    type: str,
    message: str,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> Event:
    """Add an activity-stream event to the current transaction (committed with the change it describes)."""
    event = Event(
        type=type,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        data=data or {},
    )
    db.add(event)
    return event
