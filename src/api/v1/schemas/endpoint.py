from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict

from src.api.v1.schemas.common import CursorPage


class EndpointCreate(BaseModel):
    name: str
    url: AnyHttpUrl
    secret: str | None = None


class EndpointUpdate(BaseModel):
    name: str | None = None
    url: AnyHttpUrl | None = None
    secret: str | None = None
    is_active: bool | None = None


class EndpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    is_active: bool
    created_at: datetime
    failure_count: int


EndpointListResponse = CursorPage[EndpointResponse]

