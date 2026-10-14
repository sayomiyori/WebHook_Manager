from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class LegacyRateLimitModel(Base):
    __tablename__ = "legacy_rate_limits"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamps: Mapped[list[datetime]] = mapped_column(ARRAY(DateTime(timezone=True)))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
