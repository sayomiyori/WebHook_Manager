from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError
from src.domain.enums import TelegramWebhookStatus
from src.infrastructure.db.models.telegram_bot_webhook import (
    TelegramBotWebhookModel as Webhook,
)


class TelegramWebhookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self,
        bot_id: UUID,
        tenant_id: UUID,
        url: str,
        encrypted: str,
        digest: str,
        *,
        replace_url: bool = False,
    ) -> Webhook:
        await self.session.execute(
            insert(Webhook)
            .values(
                bot_id=bot_id,
                tenant_id=tenant_id,
                url=url,
                encrypted_secret=encrypted,
                secret_digest=digest,
            )
            .on_conflict_do_nothing(index_elements=[Webhook.bot_id])
        )
        row = (
            await self.session.execute(
                select(Webhook)
                .where(Webhook.bot_id == bot_id, Webhook.tenant_id == tenant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        changing_url = replace_url and row.url != url
        if row.state == "configured" and not changing_url:
            return row
        now = (await self.session.execute(select(func.clock_timestamp()))).scalar_one()
        if row.claim_id and row.claim_deadline and row.claim_deadline > now:
            raise ConflictError()
        if changing_url:
            # Keep the secret so updates queued at the old URL can authenticate.
            row.url = url
        row.claim_id = uuid4()
        row.claim_deadline = now + timedelta(seconds=60)
        row.state = "configuring"
        row.updated_at = now
        return row

    async def finish(
        self,
        bot_id: UUID,
        tenant_id: UUID,
        claim_id: UUID,
        status: TelegramWebhookStatus,
    ) -> bool:
        result = await self.session.execute(
            update(Webhook)
            .where(
                Webhook.bot_id == bot_id,
                Webhook.tenant_id == tenant_id,
                Webhook.claim_id == claim_id,
                Webhook.claim_deadline > func.clock_timestamp(),
            )
            .values(
                state=status.value,
                claim_id=None,
                claim_deadline=None,
                updated_at=func.clock_timestamp(),
            )
            .returning(Webhook.bot_id)
        )
        return result.scalar_one_or_none() is not None
