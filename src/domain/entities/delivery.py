from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.entities.base import BaseEntity
from src.domain.enums import DeliveryStatus


@dataclass(frozen=False, slots=True)
class DeliveryAttempt(BaseEntity):
    """Webhook delivery attempt entity."""

    event_id: UUID
    endpoint_id: UUID
    attempt_number: int
    status: DeliveryStatus
    response_code: int | None
    response_body: str | None
    error_message: str | None
    attempted_at: datetime
    retried_from_id: UUID | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None
    resolution_reference: str | None = None
