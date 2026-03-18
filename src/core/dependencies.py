from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.cache.rate_limiter import RateLimiter
from src.infrastructure.cache.redis_client import get_redis
from src.infrastructure.db.base import get_db_session
from src.infrastructure.db.repositories.api_key_repository import (
    PostgresApiKeyRepository,
)
from src.infrastructure.db.repositories.delivery_attempt_repository import (
    PostgresDeliveryAttemptRepository,
)
from src.infrastructure.db.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from src.infrastructure.db.repositories.source_repository import (
    PostgresSourceRepository,
)
from src.infrastructure.db.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository
from src.infrastructure.db.repositories.webhook_event_repository import (
    PostgresWebhookEventRepository,
)
from src.services.auth_service import AuthService
from src.services.delivery_service import DeliveryService
from src.services.endpoint_service import EndpointService
from src.services.event_service import EventService
from src.services.subscription_service import SubscriptionService


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


def get_endpoint_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PostgresEndpointRepository:
    return PostgresEndpointRepository(session)


def get_event_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PostgresWebhookEventRepository:
    return PostgresWebhookEventRepository(session)


def get_subscription_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PostgresSubscriptionRepository:
    return PostgresSubscriptionRepository(session)


def get_source_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PostgresSourceRepository:
    return PostgresSourceRepository(session)


def get_endpoint_service(
    repo: PostgresEndpointRepository = Depends(get_endpoint_repo),  # noqa: B008
) -> EndpointService:
    return EndpointService(repo)


def get_event_service(
    repo: PostgresWebhookEventRepository = Depends(get_event_repo),  # noqa: B008
    subs: PostgresSubscriptionRepository = Depends(get_subscription_repo),  # noqa: B008
) -> EventService:
    return EventService(repo, subs)


def get_subscription_service(
    repo: PostgresSubscriptionRepository = Depends(get_subscription_repo),  # noqa: B008
) -> SubscriptionService:
    return SubscriptionService(repo)


def get_delivery_attempt_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PostgresDeliveryAttemptRepository:
    return PostgresDeliveryAttemptRepository(session)


def get_delivery_service(
    attempts: PostgresDeliveryAttemptRepository = Depends(get_delivery_attempt_repo),  # noqa: B008
    endpoints: PostgresEndpointRepository = Depends(get_endpoint_repo),  # noqa: B008
) -> DeliveryService:
    return DeliveryService(attempts, endpoints)


def get_user_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PostgresUserRepository:
    return PostgresUserRepository(session)


def get_api_key_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PostgresApiKeyRepository:
    return PostgresApiKeyRepository(session)


def get_auth_service(
    api_keys: PostgresApiKeyRepository = Depends(get_api_key_repo),  # noqa: B008
    users: PostgresUserRepository = Depends(get_user_repo),  # noqa: B008
) -> AuthService:
    return AuthService(api_keys=api_keys, users=users)


def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_redis())

