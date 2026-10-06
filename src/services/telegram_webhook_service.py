from __future__ import annotations

import secrets
from uuid import UUID

from pydantic import SecretStr

from src.api.v1.schemas.bots import WebhookProvisionView
from src.core.config import Settings
from src.core.exceptions import ForbiddenError, NotFoundError
from src.domain.enums import TelegramWebhookStatus
from src.infrastructure.db.repositories.telegram_bot_repository import (
    TelegramBotRepository,
)
from src.infrastructure.db.repositories.telegram_webhook_repository import (
    TelegramWebhookRepository,
)
from src.infrastructure.platform.clients import AuthFortressClient, TelegramClient
from src.infrastructure.platform.credentials import BotCredentials
from src.infrastructure.platform.errors import PlatformError
from src.infrastructure.platform.webhook_credentials import WebhookCredentials


class TelegramWebhookService:
    def __init__(
        self,
        bots: TelegramBotRepository,
        repo: TelegramWebhookRepository,
        issuer: AuthFortressClient,
        telegram: TelegramClient,
        config: Settings,
    ) -> None:
        self.bots, self.repo, self.issuer, self.telegram, self.config = (
            bots,
            repo,
            issuer,
            telegram,
            config,
        )

    async def provision(
        self, tenant_id: UUID, bot_id: UUID, bearer: SecretStr, dry_run: bool
    ) -> WebhookProvisionView:
        context = await self.issuer.authorize(tenant_id, bearer, "bot.manage")
        bot = await self.bots.get(bot_id, tenant_id)
        if bot is None:
            raise NotFoundError()
        if not bot.is_active:
            raise ForbiddenError()
        url = (
            bot.webhook.url
            if bot.webhook is not None
            else f"{self.config.TELEGRAM_WEBHOOK_ORIGIN}/webhooks/telegram/{bot_id}"
        )
        if dry_run:
            return WebhookProvisionView(
                bot_id=bot_id, tenant_id=tenant_id, webhook_url=url, dry_run=True
            )
        key = self.config.BOT_CREDENTIALS_KEY
        if key is None:
            raise PlatformError()
        cipher = WebhookCredentials(key)
        secret = SecretStr(secrets.token_urlsafe(32))
        row = await self.repo.claim(
            bot_id,
            tenant_id,
            url,
            cipher.encrypt(bot_id, tenant_id, secret),
            cipher.digest(secret),
        )
        if row.state == "configured":
            return WebhookProvisionView(
                bot_id=bot_id,
                tenant_id=tenant_id,
                webhook_url=row.url,
                webhook_status="configured",
            )
        claim_id = row.claim_id
        if claim_id is None:
            raise PlatformError()
        await self.repo.session.commit()
        try:
            fresh = await self.issuer.authorize(tenant_id, bearer, "bot.manage")
            current = await self.bots.get(bot_id, tenant_id)
            if (
                fresh.user_id != context.user_id
                or current is None
                or not current.is_active
            ):
                raise ForbiddenError()
        except (PlatformError, ForbiddenError):
            await self.repo.finish(
                bot_id, tenant_id, claim_id, TelegramWebhookStatus.FAILED
            )
            await self.repo.session.commit()
            raise
        try:
            await self.telegram.set_webhook(
                BotCredentials(key).decrypt(
                    current.credentials_encrypted, bot_id, tenant_id
                ),
                row.url,
                cipher.decrypt(row.encrypted_secret, bot_id, tenant_id),
            )
        except PlatformError as error:
            state = (
                TelegramWebhookStatus.FAILED
                if error.status_code in {400, 502}
                else TelegramWebhookStatus.UNKNOWN
            )
            await self.repo.finish(bot_id, tenant_id, claim_id, state)
            await self.repo.session.commit()
            raise
        finished = await self.repo.finish(
            bot_id, tenant_id, claim_id, TelegramWebhookStatus.CONFIGURED
        )
        await self.repo.session.commit()
        if not finished:
            raise PlatformError()
        return WebhookProvisionView(
            bot_id=bot_id,
            tenant_id=tenant_id,
            webhook_url=row.url,
            webhook_status="configured",
        )
