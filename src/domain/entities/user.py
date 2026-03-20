from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities.base import BaseEntity


@dataclass(frozen=False, slots=True)
class User(BaseEntity):
    """User domain entity."""

    email: str
    hashed_password: str
    is_active: bool

