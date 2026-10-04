from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _configure_test_environment() -> None:
    """Refuse implicit application databases, including values from .env."""
    from sqlalchemy.engine import make_url

    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url or not (make_url(database_url).database or "").endswith(
        "_test"
    ):
        raise RuntimeError(
            "TEST_DATABASE_URL must explicitly name a database ending _test"
        )
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not redis_url:
        raise RuntimeError("TEST_REDIS_URL must explicitly select isolated test Redis")
    os.environ["DATABASE_URL"] = database_url
    os.environ["REDIS_URL"] = redis_url
    os.environ["CELERY_BROKER_URL"] = redis_url
    os.environ.setdefault(
        "SECRET_KEY", "local-test-only-key-with-at-least-32-characters"
    )


_configure_test_environment()

from src.api.main import app  # noqa: E402
from src.core.dependencies import get_session  # noqa: E402
from src.core.security import generate_api_key  # noqa: E402
from src.domain.entities.api_key import ApiKey  # noqa: E402
from src.domain.entities.user import User  # noqa: E402
from src.infrastructure.db import models as _models  # noqa: F401, E402
from src.infrastructure.db.base import engine  # noqa: E402
from src.infrastructure.db.repositories.api_key_repository import (  # noqa: E402
    PostgresApiKeyRepository,
)
from src.infrastructure.db.repositories.user_repository import (  # noqa: E402
    PostgresUserRepository,
)


@pytest_asyncio.fixture
async def db_session(monkeypatch) -> AsyncSession:
    # Migrations must be applied before pytest; tests may commit savepoints only.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            from contextlib import asynccontextmanager

            from src.infrastructure.queue import dispatcher

            @asynccontextmanager
            async def shared_session():
                yield session

            monkeypatch.setattr(dispatcher, "async_session_maker", shared_session)
            try:
                yield session
            finally:
                await transaction.rollback()


@pytest.fixture(autouse=True)
def restore_celery_configuration():
    from src.infrastructure.queue.celery_app import celery_app

    eager = celery_app.conf.task_always_eager
    propagates = celery_app.conf.task_eager_propagates
    yield
    celery_app.conf.task_always_eager = eager
    celery_app.conf.task_eager_propagates = propagates


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    repo = PostgresUserRepository(db_session)
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        email=f"test-{uuid4()}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    return await repo.create(user)


@pytest_asyncio.fixture
async def api_key(db_session: AsyncSession, test_user: User) -> tuple[ApiKey, str]:
    repo = PostgresApiKeyRepository(db_session)
    plain, prefix, key_hash = generate_api_key()
    now = datetime.now(UTC)
    entity = ApiKey(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        key_prefix=prefix,
        key_hash=key_hash,
        name="test",
        owner_id=test_user.id,
        last_used_at=None,
        is_active=True,
    )
    created = await repo.create(entity)
    return created, plain


@pytest_asyncio.fixture
async def auth_headers(api_key: tuple[ApiKey, str]) -> dict[str, str]:
    _, plaintext = api_key
    return {"X-API-Key": plaintext}
