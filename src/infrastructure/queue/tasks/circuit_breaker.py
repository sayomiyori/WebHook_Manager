from __future__ import annotations

from redis.asyncio import Redis


class CircuitBreaker:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def record_failure(self, *, endpoint_id: str, ttl_seconds: int = 600) -> int:
        key = f"cb:endpoint:{endpoint_id}"
        value = await self._redis.incr(key)
        await self._redis.expire(key, ttl_seconds)
        return int(value)

    async def reset(self, *, endpoint_id: str) -> None:
        await self._redis.delete(f"cb:endpoint:{endpoint_id}")

