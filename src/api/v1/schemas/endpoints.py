from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EndpointCreateRequest(BaseModel):
    name: str
    url: str
    secret: str | None = None
    is_active: bool = True


class EndpointUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    secret: str | None = None
    is_active: bool | None = None


class EndpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    url: str
    owner_id: UUID
    secret: str | None
    is_active: bool
    failure_count: int

