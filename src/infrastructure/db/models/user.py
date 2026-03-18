from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.db.base import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    api_keys = relationship(
        "ApiKeyModel",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sources = relationship(
        "SourceModel",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    endpoints = relationship(
        "EndpointModel",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    subscriptions = relationship(
        "SubscriptionModel",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

