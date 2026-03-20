from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=False, slots=True)
class BaseEntity:
    """Base type for all domain entities."""

    id: UUID
    created_at: datetime
    updated_at: datetime

