from __future__ import annotations

import asyncio
from uuid import uuid4

from src.core.exceptions import RateLimitError
from src.infrastructure.cache.bot_registration_limiter import (
    ADMISSION_LUA,
    BotRegistrationLimiter,
)
from src.infrastructure.cache.redis_client import get_redis


async def test_concurrent_registration_quota_is_atomic():
    redis = get_redis()
    limiter = BotRegistrationLimiter(redis, 10)
    user, tenant = uuid4(), uuid4()
    results = await asyncio.gather(
        *[limiter.admit(user, tenant) for _ in range(30)], return_exceptions=True
    )
    assert results.count(None) == 10
    assert sum(isinstance(result, RateLimitError) for result in results) == 20
    assert await redis.zcard(f"platform:bot-register:{user}:{tenant}") == 10


async def test_exact_trailing_boundary_expires_without_sleep():
    # One atomic Redis script establishes scores against the same server TIME.
    redis = get_redis()
    key = "platform:boundary:" + str(uuid4())
    setup_and_admit = (
        """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
redis.call('ZADD', KEYS[1], now - 60000, 'boundary')
redis.call('ZADD', KEYS[1], now, 'current')
"""
        + ADMISSION_LUA
    )
    assert await redis.eval(setup_and_admit, 1, key, "2", str(uuid4())) == 1
    assert await redis.zscore(key, "boundary") is None
    assert await redis.zcard(key) == 2


async def test_same_timestamp_admissions_do_not_collapse_and_denial_keeps_expiry():
    redis = get_redis()
    key = "platform:timestamps:" + str(uuid4())
    # Stub the clock only at its Lua boundary, while using real Redis operations.
    frozen = ADMISSION_LUA.replace(
        "local t = redis.call('TIME')", "local t = {12345, 0}"
    )
    for _ in range(3):
        assert await redis.eval(frozen, 1, key, "3", str(uuid4())) == 1
    assert await redis.zcard(key) == 3
    scored = await redis.zrange(key, 0, -1, withscores=True)
    assert len({score for _, score in scored}) == 1
    # Make the no-extension check independent of wall-clock passage.
    await redis.pexpire(key, 10000)
    assert await redis.eval(frozen, 1, key, "3", str(uuid4())) == 0
    assert 0 < await redis.pttl(key) <= 10000
