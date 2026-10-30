from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator

_EMAIL = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)


def _normalize_email(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > 320 or _EMAIL.fullmatch(normalized) is None:
        raise ValueError("Invalid email")
    return normalized


def _trim_email(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > 320:
        raise ValueError("Invalid email")
    return normalized


Email = Annotated[str, AfterValidator(_normalize_email)]
LoginEmail = Annotated[str, AfterValidator(_trim_email)]


class RegisterRequest(BaseModel):
    email: Email
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 6 or len(value.encode("utf-8")) > 72:
            raise ValueError(
                "Password must be at least 6 characters and at most 72 UTF-8 bytes"
            )
        return value


class RegisterResponse(BaseModel):
    user_id: UUID


class LoginRequest(BaseModel):
    email: LoginEmail
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 1 or len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be between 1 and 72 UTF-8 bytes")
        return value


class LoginResponse(BaseModel):
    user_id: UUID


class ApiKeyCreateRequest(BaseModel):
    name: str


class ApiKeyCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    key_prefix: str
    created_at: datetime
    key: str


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    is_active: bool
    created_at: datetime
