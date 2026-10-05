from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from src.infrastructure.cache.bot_registration_limiter import BotRegistrationLimiter
from src.infrastructure.db.models.telegram_bot import TelegramBotModel
from src.infrastructure.db.repositories.telegram_bot_repository import (
    TelegramBotRepository,
)
from src.infrastructure.platform.clients import AuthFortressClient, TelegramClient
from src.infrastructure.platform.credentials import BotCredentials


class BotService:
    def __init__(
        self,
        repo: TelegramBotRepository,
        issuer: AuthFortressClient,
        telegram: TelegramClient,
        credentials: BotCredentials,
        limiter: BotRegistrationLimiter,
    ) -> None:
        self._repo = repo
        self._issuer = issuer
        self._telegram = telegram
        self._credentials = credentials
        self._limiter = limiter

    async def create(
        self, tenant_id: UUID, bearer: SecretStr, name: str, token: SecretStr
    ) -> TelegramBotModel:
        context = await self._issuer.authorize(tenant_id, bearer, "bot.manage")
        await self._limiter.admit(context.user_id, tenant_id)
        profile = await self._telegram.get_me(token)
        fresh = await self._issuer.authorize(tenant_id, bearer, "bot.manage")
        if fresh.user_id != context.user_id:
            raise ForbiddenError()
        bot_id = uuid4()
        bot = TelegramBotModel(
            id=bot_id,
            tenant_id=tenant_id,
            created_by=context.user_id,
            name=name,
            telegram_bot_id=profile.id,
            username=profile.username,
            credentials_encrypted=self._credentials.encrypt(bot_id, tenant_id, token),
        )
        self._repo.session.add(bot)
        try:
            await self._repo.session.commit()
        except IntegrityError as error:
            await self._repo.session.rollback()
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ConflictError() from None
            raise
        await self._repo.session.refresh(bot)
        return bot

    async def get(self, bot_id: UUID, tenant_id: UUID) -> TelegramBotModel:
        bot = await self._repo.get(bot_id, tenant_id)
        if bot is None:
            raise NotFoundError()
        return bot

    async def list(
        self, tenant_id: UUID, cursor: UUID | None, limit: int
    ) -> list[TelegramBotModel]:
        return await self._repo.list(tenant_id, cursor, limit)

    async def deactivate(self, bot_id: UUID, tenant_id: UUID) -> TelegramBotModel:
        await self.get(bot_id, tenant_id)
        await self._repo.deactivate(bot_id, tenant_id)
        await self._repo.session.commit()
        return await self.get(bot_id, tenant_id)

    async def context(self, bot_id: UUID) -> TelegramBotModel:
        bot = await self._repo.get(bot_id)
        if bot is None:
            raise NotFoundError()
        if not bot.is_active:
            raise ForbiddenError()
        await self._issuer.tenant_active(bot.tenant_id)
        # Force a fresh SELECT, not the request session's identity-map state.
        fresh = await self._repo.get(bot_id)
        if fresh is None:
            raise NotFoundError()
        if not fresh.is_active:
            raise ForbiddenError()
        return fresh
