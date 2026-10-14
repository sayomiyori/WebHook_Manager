from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from src.infrastructure.cache.rate_limiter import RateLimiter
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.models import LegacyRateLimitModel


@pytest.mark.asyncio
async def test_concurrent_instances_share_quota_and_count_rejections() -> None:
    key = f"ingest:{uuid4()}"
    allowed = await asyncio.gather(
        *(RateLimiter().allow(key=key, limit=3) for _ in range(12))
    )
    assert sum(allowed) == 3
    assert await RateLimiter().allow(key=key, limit=3) is False
    async with async_session_maker() as session:
        row = await session.get(
            LegacyRateLimitModel, hashlib.sha256(key.encode()).hexdigest()
        )
        assert row is not None
        assert len(row.timestamps) == 4
        assert row.key_hash != key
        assert row.timestamps == sorted(row.timestamps)


@pytest.mark.asyncio
async def test_window_expiration_and_scope_isolation() -> None:
    key = f"ingest:{uuid4()}"
    limiter = RateLimiter()
    assert await limiter.allow(key=key, limit=1)
    assert not await limiter.allow(key=key, limit=1)
    assert await limiter.allow(key=f"read:{key}", limit=1)
    async with async_session_maker.begin() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        await session.execute(
            update(LegacyRateLimitModel)
            .where(
                LegacyRateLimitModel.key_hash
                == hashlib.sha256(key.encode()).hexdigest()
            )
            .values(timestamps=[now - timedelta(seconds=61)], expires_at=now)
        )
    assert await RateLimiter().allow(key=key, limit=1)


@pytest.mark.asyncio
async def test_expired_other_keys_are_reclaimed() -> None:
    key = f"ingest:{uuid4()}"
    assert await RateLimiter().allow(key=key, limit=1)
    hashed = hashlib.sha256(key.encode()).hexdigest()
    async with async_session_maker.begin() as session:
        await session.execute(
            update(LegacyRateLimitModel)
            .where(LegacyRateLimitModel.key_hash == hashed)
            .values(expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert await RateLimiter().allow(key=f"ingest:{uuid4()}", limit=1)
    async with async_session_maker() as session:
        assert await session.get(LegacyRateLimitModel, hashed) is None


@pytest.mark.asyncio
async def test_sliding_window_retains_recent_rejected_requests() -> None:
    key = f"ingest:{uuid4()}"
    hashed = hashlib.sha256(key.encode()).hexdigest()
    assert await RateLimiter().allow(key=key, limit=2)
    async with async_session_maker.begin() as session:
        now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
        await session.execute(
            update(LegacyRateLimitModel)
            .where(LegacyRateLimitModel.key_hash == hashed)
            .values(
                timestamps=[now - timedelta(seconds=61), now - timedelta(seconds=1)],
                expires_at=now + timedelta(seconds=60),
            )
        )
    assert await RateLimiter().allow(key=key, limit=2)
    assert not await RateLimiter().allow(key=key, limit=2)
    async with async_session_maker() as session:
        row = await session.get(LegacyRateLimitModel, hashed)
        assert row is not None
        assert len(row.timestamps) == 3
        assert all(stamp > now - timedelta(seconds=60) for stamp in row.timestamps)


@pytest.mark.asyncio
async def test_expired_locked_key_does_not_block_other_keys() -> None:
    key = f"ingest:{uuid4()}"
    hashed = hashlib.sha256(key.encode()).hexdigest()
    assert await RateLimiter().allow(key=key, limit=1)
    async with async_session_maker.begin() as session:
        now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
        await session.execute(
            update(LegacyRateLimitModel)
            .where(LegacyRateLimitModel.key_hash == hashed)
            .values(timestamps=[now - timedelta(seconds=61)], expires_at=now)
        )
    async with async_session_maker.begin() as session:
        await session.execute(
            select(LegacyRateLimitModel)
            .where(LegacyRateLimitModel.key_hash == hashed)
            .with_for_update()
        )
        waiting = asyncio.create_task(RateLimiter().allow(key=key, limit=1))
        assert await asyncio.wait_for(
            RateLimiter().allow(key=f"ingest:{uuid4()}", limit=1), timeout=5
        )
        assert not waiting.done()
    assert await asyncio.wait_for(waiting, timeout=5)
    assert not await RateLimiter().allow(key=key, limit=1)


@pytest.mark.asyncio
async def test_invalid_quota_fails_closed() -> None:
    assert not await RateLimiter().allow(key="unused", limit=0)
    with pytest.raises(ValueError, match="window must be positive"):
        await RateLimiter().allow(key="unused", limit=1, window_seconds=0)
