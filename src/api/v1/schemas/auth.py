from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApiKeyCreateRequest(BaseModel):
    owner_id: UUID
    name: str


class ApiKeyCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    key_prefix: str
    name: str
    owner_id: UUID
    last_used_at: datetime | None
    is_active: bool

    raw_key: str


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    key_prefix: str
    name: str
    owner_id: UUID
    last_used_at: datetime | None
    is_active: bool

