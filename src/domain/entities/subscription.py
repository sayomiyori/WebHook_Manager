from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.domain.entities.base import BaseEntity


@dataclass(frozen=False, slots=True)
class Subscription(BaseEntity):
    endpoint_id: UUID
    source_id: UUID
    owner_id: UUID
    event_type_filter: list[str] = field(default_factory=lambda: ["*"])
    is_active: bool = True

