from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)


class AnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ingress_event_id: UUID
    job_id: UUID
    text: Annotated[StrictStr, Field(min_length=1, max_length=4096)]

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str) -> str:
        value.encode("utf-8")
        if not value.strip() or "\x00" in value:
            raise ValueError("Invalid answer text")
        return value


class AnswerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: UUID
    event_type: Literal["telegram.answer.created"]
    schema_version: Literal[1]
    occurred_at: AwareDatetime
    tenant_id: UUID
    bot_id: UUID
    correlation_id: UUID
    idempotency_key: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    payload: AnswerPayload

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Invalid schema version")
        return value

    @model_validator(mode="after")
    def identity(self) -> "AnswerEnvelope":
        if (
            self.idempotency_key != f"telegram-answer:{self.payload.ingress_event_id}"
            or self.occurred_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("Invalid answer identity")
        return self


class AnswerReceipt(BaseModel):
    event_id: UUID
    delivery_id: UUID
    state: Literal[
        "pending", "processing", "succeeded", "failed", "unknown", "cancelled"
    ]
