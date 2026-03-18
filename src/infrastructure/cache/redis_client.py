from __future__ import annotations

from functools import lru_cache
from typing import cast

from redis.asyncio import Redis

from src.core.config import settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return cast(Redis, Redis.from_url(str(settings.REDIS_URL), decode_responses=True))

