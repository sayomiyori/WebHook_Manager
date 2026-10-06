from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.telegram_ingress import (
    TelegramIngressEnvelope,
    TelegramMessagePayload,
)
from src.core.exceptions import ConflictError
from src.infrastructure.db.models.platform_ingress_outbox import (
    PlatformIngressOutboxModel as Outbox,
)
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel as Event,
)
from src.infrastructure.platform.telegram_update import canonical_digest, identifier


class TelegramIngressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def admit(
        self,
        bot_id: UUID,
        tenant_id: UUID,
        raw: dict[str, object],
        payload: TelegramMessagePayload | None,
    ) -> tuple[Event, bool]:
        event_id, correlation_id = uuid4(), uuid4()
        update_id, digest = identifier(raw.get("update_id")), canonical_digest(raw)
        envelope = (
            None
            if payload is None
            else TelegramIngressEnvelope(
                event_id=event_id,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                occurred_at=datetime.now(UTC),
                idempotency_key=f"telegram:{bot_id}:{update_id}",
                payload=payload,
            ).model_dump(mode="json")
        )
        row = (
            await self.session.execute(
                insert(Event)
                .values(
                    id=event_id,
                    correlation_id=correlation_id,
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    update_id=update_id,
                    digest=digest,
                    raw=raw,
                    envelope=envelope,
                    state="ignored" if payload is None else "accepted",
                )
                .on_conflict_do_nothing(index_elements=[Event.bot_id, Event.update_id])
                .returning(Event)
            )
        ).scalar_one_or_none()
        if row is None:
            existing = (
                await self.session.execute(
                    select(Event).where(
                        Event.bot_id == bot_id,
                        Event.tenant_id == tenant_id,
                        Event.update_id == update_id,
                    )
                )
            ).scalar_one()
            if existing.digest != digest:
                raise ConflictError()
            return existing, True
        if payload is not None:
            self.session.add(
                Outbox(
                    id=uuid4(), ingress_id=row.id, tenant_id=tenant_id, bot_id=bot_id
                )
            )
            await self.session.flush()
        return row, False
