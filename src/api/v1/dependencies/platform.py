from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, settings
from src.core.dependencies import get_session
from src.infrastructure.cache.bot_registration_limiter import BotRegistrationLimiter
from src.infrastructure.cache.redis_client import get_redis
from src.infrastructure.db.repositories.telegram_bot_repository import (
    TelegramBotRepository,
)
from src.infrastructure.db.repositories.telegram_ingress_repository import (
    TelegramIngressRepository,
)
from src.infrastructure.db.repositories.telegram_webhook_repository import (
    TelegramWebhookRepository,
)
from src.infrastructure.platform.clients import AuthFortressClient, TelegramClient
from src.infrastructure.platform.credentials import BotCredentials
from src.infrastructure.platform.errors import PlatformError
from src.services.bot_service import BotService
from src.services.telegram_ingress_service import TelegramIngressService
from src.services.telegram_webhook_service import TelegramWebhookService

bearer_scheme = HTTPBearer(auto_error=False)


def get_platform_settings() -> Settings:
    return settings


def require_platform(config: Settings = Depends(get_platform_settings)) -> Settings:  # noqa: B008
    if not config.PLATFORM_BOTS_ENABLED:
        raise PlatformError()
    return config


def require_telegram(config: Settings = Depends(require_platform)) -> Settings:  # noqa: B008
    if not config.PLATFORM_TELEGRAM_ENABLED:
        raise PlatformError()
    return config


def get_issuer(config: Settings = Depends(require_platform)) -> AuthFortressClient:  # noqa: B008
    if not config.AUTHFORTRESS_BASE_URL:
        raise PlatformError()
    return AuthFortressClient(
        config.AUTHFORTRESS_BASE_URL, config.AUTHFORTRESS_WEBHOOK_SERVICE_KEY
    )


def get_telegram() -> TelegramClient:
    return TelegramClient()


def get_registration_limiter(
    config: Settings = Depends(require_platform),  # noqa: B008
) -> BotRegistrationLimiter:
    return BotRegistrationLimiter(get_redis(), config.RATE_LIMIT_BOT_REGISTER)


def get_bearer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
) -> SecretStr:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise PlatformError(401)
    return SecretStr(credentials.credentials)


async def require_read(
    tenant_id: UUID,
    bearer: SecretStr = Depends(get_bearer),  # noqa: B008
    issuer: AuthFortressClient = Depends(get_issuer),  # noqa: B008
) -> None:
    await issuer.authorize(tenant_id, bearer, "bot.read")


async def require_manage(
    tenant_id: UUID,
    bearer: SecretStr = Depends(get_bearer),  # noqa: B008
    issuer: AuthFortressClient = Depends(get_issuer),  # noqa: B008
) -> None:
    await issuer.authorize(tenant_id, bearer, "bot.manage")


def require_service_key(
    key: str | None = Header(None, alias="X-Service-Key"),
    config: Settings = Depends(require_platform),  # noqa: B008
) -> None:
    expected = config.WEBHOOK_AGENT_CONTEXT_KEY
    if not expected:
        raise PlatformError()
    if (
        not key
        or not key.isascii()
        or len(key) > 256
        or not secrets.compare_digest(
            key.encode(), expected.get_secret_value().encode()
        )
    ):
        raise HTTPException(status_code=401, detail="Invalid service key")


def get_bot_service(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    issuer: AuthFortressClient = Depends(get_issuer),  # noqa: B008
    telegram: TelegramClient = Depends(get_telegram),  # noqa: B008
    limiter: BotRegistrationLimiter = Depends(get_registration_limiter),  # noqa: B008
    config: Settings = Depends(require_platform),  # noqa: B008
) -> BotService:
    if config.BOT_CREDENTIALS_KEY is None:
        raise PlatformError()
    return BotService(
        TelegramBotRepository(session),
        issuer,
        telegram,
        BotCredentials(config.BOT_CREDENTIALS_KEY),
        limiter,
    )


def get_webhook_service(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    issuer: AuthFortressClient = Depends(get_issuer),  # noqa: B008
    telegram: TelegramClient = Depends(get_telegram),  # noqa: B008
    config: Settings = Depends(require_telegram),  # noqa: B008
) -> TelegramWebhookService:  # noqa: B008
    return TelegramWebhookService(
        TelegramBotRepository(session),
        TelegramWebhookRepository(session),
        issuer,
        telegram,
        config,
    )


def get_ingress_service(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    issuer: AuthFortressClient = Depends(get_issuer),  # noqa: B008
) -> TelegramIngressService:  # noqa: B008
    return TelegramIngressService(
        TelegramBotRepository(session), TelegramIngressRepository(session), issuer
    )
