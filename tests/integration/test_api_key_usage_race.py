"""A stale usage update must never recreate a revoked credential."""

from uuid import uuid4

import pytest

from src.core.exceptions import NotFoundError
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.repositories.api_key_repository import (
    PostgresApiKeyRepository,
)
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository
from src.services.auth_service import AuthService


async def test_stale_usage_update_cannot_recreate_a_revoked_key():
    async with async_session_maker() as first, async_session_maker() as second:
        repo = PostgresApiKeyRepository(first)
        auth = AuthService(repo, PostgresUserRepository(first))
        user = await auth.register_user(
            f"usage-race-{uuid4()}@example.com", "local-test-password"
        )
        key, plaintext = await auth.create_api_key(user.id, "Usage race")
        await PostgresApiKeyRepository(second).delete(key.id)
        with pytest.raises(NotFoundError):
            await repo.update(key)
        await first.rollback()
        assert (
            await AuthService(
                PostgresApiKeyRepository(second), PostgresUserRepository(second)
            ).verify_api_key(plaintext)
            is None
        )
