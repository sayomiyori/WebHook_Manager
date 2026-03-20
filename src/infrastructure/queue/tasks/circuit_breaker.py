from __future__ import annotations

from typing import Any, cast

from redis import Redis as SyncRedis
from redis.asyncio import Redis as AsyncRedis


class CircuitBreaker:
    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    async def record_failure(self, *, endpoint_id: str, ttl_seconds: int = 600) -> int:
        key = f"cb:endpoint:{endpoint_id}"
        value = await self._redis.incr(key)
        await self._redis.expire(key, ttl_seconds)
        return int(value)

    async def reset(self, *, endpoint_id: str) -> None:
        await self._redis.delete(f"cb:endpoint:{endpoint_id}")


class SyncCircuitBreaker:
    """Sync Redis circuit breaker for use inside Celery sync tasks."""

    def __init__(self, redis: SyncRedis) -> None:
        self._redis = redis

    def record_failure(self, *, endpoint_id: str, ttl_seconds: int = 600) -> int:
        key = f"cb:endpoint:{endpoint_id}"
        value = self._redis.incr(key)
        self._redis.expire(key, ttl_seconds)
        if isinstance(value, int):
            return value
        return int(cast(Any, value))

    def reset(self, *, endpoint_id: str) -> None:
        self._redis.delete(f"cb:endpoint:{endpoint_id}")

    def get_failure_count(self, *, endpoint_id: str) -> int:
        key = f"cb:endpoint:{endpoint_id}"
        value = self._redis.get(key)
        if value is None:
            return 0
        # redis-py may return `bytes` or `str` depending on decode_responses.
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            try:
                return int(value)
            except Exception:
                return 0
        if isinstance(value, int):
            return value
        return 0

    def is_open(self, *, endpoint_id: str, threshold: int = 10) -> bool:
        return self.get_failure_count(endpoint_id=endpoint_id) >= threshold

