from __future__ import annotations

from collections.abc import Awaitable
from typing import cast
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.exceptions import RateLimitError
from src.infrastructure.platform.errors import PlatformError

# TIME and all sorted-set operations execute atomically on the Redis server.
ADMISSION_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60000)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('PEXPIRE', KEYS[1], 60000)
return 1
"""


class BotRegistrationLimiter:
    def __init__(self, redis: Redis, limit: int) -> None:
        self._redis = redis
        self._limit = limit

    async def admit(self, user_id: UUID, tenant_id: UUID) -> None:
        try:
            admitted = await cast(
                Awaitable[int],
                self._redis.eval(
                    ADMISSION_LUA,
                    1,
                    f"platform:bot-register:{user_id}:{tenant_id}",
                    str(self._limit),
                    str(uuid4()),
                ),
            )
        except RedisError:
            raise PlatformError() from None
        if admitted != 1:
            raise RateLimitError()
