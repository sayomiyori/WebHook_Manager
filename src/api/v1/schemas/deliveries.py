from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.domain.enums import DeliveryStatus


class DeliveryAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    event_id: UUID
    endpoint_id: UUID
    attempt_number: int
    status: DeliveryStatus
    response_code: int | None
    response_body: str | None
    error_message: str | None
    attempted_at: datetime


class DeliveryDispatchRequest(BaseModel):
    event_id: UUID
    endpoint_id: UUID

