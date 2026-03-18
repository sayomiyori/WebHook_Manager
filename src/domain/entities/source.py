from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.domain.entities.base import BaseEntity


@dataclass(frozen=False, slots=True)
class Source(BaseEntity):
    name: str
    slug: str
    owner_id: UUID
    is_active: bool

