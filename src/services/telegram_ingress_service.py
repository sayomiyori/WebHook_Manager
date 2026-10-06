from __future__ import annotations

import re
import secrets
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select

from src.core.exceptions import ForbiddenError, NotFoundError
from src.infrastructure.db.models.telegram_bot import TelegramBotModel
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel,
)
from src.infrastructure.db.repositories.telegram_bot_repository import (
    TelegramBotRepository,
)
from src.infrastructure.db.repositories.telegram_ingress_repository import (
    TelegramIngressRepository,
)
from src.infrastructure.platform.clients import AuthFortressClient
from src.infrastructure.platform.errors import PlatformError
from src.infrastructure.platform.telegram_update import normalize_update
from src.infrastructure.platform.webhook_credentials import WebhookCredentials


class TelegramIngressService:
    def __init__(
        self,
        bots: TelegramBotRepository,
        repo: TelegramIngressRepository,
        issuer: AuthFortressClient,
    ) -> None:
        self.bots, self.repo, self.issuer = bots, repo, issuer

    async def authenticate(self, bot_id: UUID, secret: SecretStr) -> TelegramBotModel:
        bot = await self.bots.get(bot_id)
        if bot is None:
            raise NotFoundError()
        raw = secret.get_secret_value()
        if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", raw) is None:
            raise PlatformError(401)
        if bot.webhook is None or bot.webhook.state == "failed":
            raise ForbiddenError()
        if not secrets.compare_digest(
            WebhookCredentials.digest(secret), bot.webhook.secret_digest
        ):
            raise PlatformError(401)
        if bot.webhook.tenant_id != bot.tenant_id or not bot.is_active:
            raise ForbiddenError()
        await self.issuer.tenant_active(bot.tenant_id)
        fresh = await self.bots.get(bot_id)
        if fresh is None or not fresh.is_active:
            raise ForbiddenError()
        return fresh

    async def admit(
        self, bot_id: UUID, secret: SecretStr, raw: dict[str, object]
    ) -> tuple[TelegramIngressEventModel, bool]:
        bot = await self.authenticate(bot_id, secret)
        payload = normalize_update(raw)
        locked = await self.repo.session.scalar(
            select(TelegramBotModel)
            .where(
                TelegramBotModel.id == bot_id,
                TelegramBotModel.tenant_id == bot.tenant_id,
                TelegramBotModel.is_active.is_(True),
            )
            .with_for_update()
        )
        if locked is None:
            raise ForbiddenError()
        result = await self.repo.admit(bot_id, bot.tenant_id, raw, payload)
        await self.repo.session.commit()
        return result
