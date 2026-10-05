from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    SecretStr,
    StringConstraints,
    field_validator,
)


class BotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=128
        ),
    ]
    token: SecretStr

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) > 256 or re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", raw) is None:
            raise ValueError("Invalid bot request")
        return value


class BotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    name: str
    telegram_bot_id: int
    username: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    webhook_status: Literal["not_configured"] = "not_configured"


class BotContext(BaseModel):
    bot_id: UUID
    tenant_id: UUID
    telegram_bot_id: int
    is_active: Literal[True] = True
