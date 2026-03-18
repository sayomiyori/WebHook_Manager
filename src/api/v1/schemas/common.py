from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class CursorPage[T](BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    next_cursor: UUID | None
    has_more: bool


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None

