from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities.base import BaseEntity


@dataclass(frozen=False, slots=True)
class User(BaseEntity):
    email: str
    hashed_password: str
    is_active: bool

