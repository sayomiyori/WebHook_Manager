from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.domain.entities.base import BaseEntity


@dataclass(frozen=False, slots=True)
class Endpoint(BaseEntity):
    """Endpoint domain entity."""

    name: str
    url: str
    owner_id: UUID
    secret: str | None
    is_active: bool
    failure_count: int = 0

