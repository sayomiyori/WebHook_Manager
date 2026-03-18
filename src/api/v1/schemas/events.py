from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EventIngestRequest(BaseModel):
    source_id: UUID
    payload: dict[str, object]
    headers: dict[str, str] = Field(default_factory=dict)
    idempotency_key: str | None = None
    event_type: str | None = None


class WebhookEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    source_id: UUID
    payload: dict[str, object]
    headers: dict[str, str]
    idempotency_key: str | None
    event_type: str | None
    received_at: datetime

