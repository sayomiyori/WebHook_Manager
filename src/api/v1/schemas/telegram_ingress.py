from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
)

TelegramId = Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)]


class TelegramMessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    update_id: TelegramId
    chat_id: TelegramId
    message_id: Annotated[StrictInt, Field(gt=0, le=2**63 - 1)]
    question: Annotated[StrictStr, Field(min_length=1, max_length=4096)]


class TelegramIngressEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: UUID
    event_type: Literal["telegram.message.received"] = "telegram.message.received"
    schema_version: Literal[1] = 1
    occurred_at: AwareDatetime
    tenant_id: UUID
    bot_id: UUID
    correlation_id: UUID
    idempotency_key: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    payload: TelegramMessagePayload

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Invalid schema version")
        return value


class IngressAck(BaseModel):
    status: Literal["accepted", "ignored", "duplicate"]
    event_id: UUID
