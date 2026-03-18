from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CursorPage[T](BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    next_cursor: UUID | None

