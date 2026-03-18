from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.entities.base import BaseEntity


@dataclass(frozen=False, slots=True)
class WebhookEvent(BaseEntity):
    source_id: UUID
    payload: dict[str, object]
    headers: dict[str, str]
    idempotency_key: str | None
    event_type: str | None
    received_at: datetime

