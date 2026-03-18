from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.entities.base import BaseEntity


@dataclass(frozen=False, slots=True)
class ApiKey(BaseEntity):
    key_prefix: str
    key_hash: str
    name: str
    owner_id: UUID
    last_used_at: datetime | None
    is_active: bool

