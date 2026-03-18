from __future__ import annotations

from datetime import UTC, datetime

from redis.asyncio import Redis


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def allow(self, *, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = datetime.now(UTC).timestamp()
        window_start = now - window_seconds
        zkey = f"rl:{key}"

        pipe = self._redis.pipeline(transaction=True)
        pipe.zremrangebyscore(zkey, 0, window_start)
        pipe.zadd(zkey, {str(now): now})
        pipe.zcard(zkey)
        pipe.expire(zkey, window_seconds)
        _, _, count, _ = await pipe.execute()
        return int(count) <= limit

