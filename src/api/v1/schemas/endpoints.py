from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from src.core.config import settings
from src.core.egress import validate_destination


class EndpointCreateRequest(BaseModel):
    name: str
    url: str
    secret: str | None = None
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        validate_destination(value, settings.DELIVERY_TRUSTED_ORIGINS)
        return value


class EndpointUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    secret: str | None = None
    is_active: bool | None = None

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        if value is not None:
            validate_destination(value, settings.DELIVERY_TRUSTED_ORIGINS)
        return value


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
