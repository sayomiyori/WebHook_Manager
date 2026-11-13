from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

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
    retried_from_id: UUID | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None
    resolution_reference: str | None = None


class DeliveryResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempted_at: AwareDatetime
    outcome: Literal["delivered", "not_delivered"]
    reference: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/ -]+$"
    )


class DeliveryDispatchRequest(BaseModel):
    event_id: UUID
    endpoint_id: UUID
