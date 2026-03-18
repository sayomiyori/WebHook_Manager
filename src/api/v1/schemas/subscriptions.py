from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SubscriptionCreateRequest(BaseModel):
    owner_id: UUID
    endpoint_id: UUID
    source_id: UUID
    event_type_filter: list[str] | None = None
    is_active: bool = True


class SubscriptionUpdateRequest(BaseModel):
    event_type_filter: list[str] | None = None
    is_active: bool | None = None


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    endpoint_id: UUID
    source_id: UUID
    owner_id: UUID
    event_type_filter: list[str]
    is_active: bool

