from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _replace_host_in_dsn(dsn: str, new_host: str) -> str:
    # Simple DSN host rewrite:
    # - postgresql+asyncpg://user:pass@postgres:5432/db -> ...@127.0.0.1:5432/db
    # - redis://redis:6379/0 -> redis://127.0.0.1:6379/0
    if "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    if "@" not in rest:
        # redis://host:port/db case without userinfo
        host_port, path = rest.split("/", 1) if "/" in rest else (rest, "")
        host, port = host_port.split(":", 1)
        new = f"{scheme}://{new_host}:{port}"
        return new + (f"/{path}" if path else "")
    userinfo, host_port_and_path = rest.split("@", 1)
    # host_port_and_path = host:port/... (for both postgres and redis)
    if "/" in host_port_and_path:
        host_port, path = host_port_and_path.split("/", 1)
    else:
        host_port, path = host_port_and_path, ""
    host, port = host_port.split(":", 1)
    new = f"{scheme}://{userinfo}@{new_host}:{port}"
    return new + (f"/{path}" if path else "")


def _load_env_file_values() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    text_env = env_path.read_text(encoding="utf-8", errors="ignore")
    values: dict[str, str] = {}
    for line in text_env.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()

    # Rewrite docker-service hosts to localhost for tests running on host.
    # This prevents asyncpg from trying to resolve `postgres` / `redis`.
    rewrite_hosts = sys.platform.startswith("win")
    for key in ("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL"):
        if key in values:
            os.environ[key] = (
                _replace_host_in_dsn(values[key], "127.0.0.1")
                if rewrite_hosts
                else values[key]
            )


_load_env_file_values()

from src.api.main import app  # noqa: E402
from src.core.dependencies import get_session  # noqa: E402
from src.core.security import generate_api_key  # noqa: E402
from src.domain.entities.api_key import ApiKey  # noqa: E402
from src.domain.entities.user import User  # noqa: E402
from src.infrastructure.db.base import async_session_maker  # noqa: E402
from src.infrastructure.db.repositories.api_key_repository import (  # noqa: E402
    PostgresApiKeyRepository,
)
from src.infrastructure.db.repositories.user_repository import (  # noqa: E402
    PostgresUserRepository,
)


async def _truncate_all(session: AsyncSession) -> None:
    await session.execute(
        text(
            "TRUNCATE TABLE "
            "delivery_attempts, webhook_events, subscriptions, endpoints, "
            "sources, api_keys, users "
            "RESTART IDENTITY CASCADE"
        )
    )
    await session.commit()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_maker() as session:
        await _truncate_all(session)
        yield session
        await _truncate_all(session)


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

