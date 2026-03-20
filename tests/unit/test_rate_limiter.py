from __future__ import annotations

import pytest

from src.infrastructure.cache.rate_limiter import RateLimiter


class _FakePipe:
    def __init__(self, count: int) -> None:
        self._count = count

    def zremrangebyscore(self, *_: object) -> _FakePipe:
        return self

    def zadd(self, *_: object) -> _FakePipe:
        return self

    def zcard(self, *_: object) -> _FakePipe:
        return self

    def expire(self, *_: object) -> _FakePipe:
        return self

    async def execute(self) -> tuple[None, None, int, None]:
        # RateLimiter expects: _, _, count, _
        return None, None, self._count, None


class _FakeRedis:
    def __init__(self, count: int) -> None:
        self._count = count

    def pipeline(self, *, transaction: bool = False) -> _FakePipe:  # noqa: ARG002
        return _FakePipe(self._count)


@pytest.mark.asyncio
async def test_rate_limiter_allows_when_count_within_limit() -> None:
    limiter = RateLimiter(redis=_FakeRedis(count=3))  # type: ignore[arg-type]
    assert await limiter.allow(key="k", limit=3, window_seconds=60) is True


@pytest.mark.asyncio
async def test_rate_limiter_denies_when_count_exceeds_limit() -> None:
    limiter = RateLimiter(redis=_FakeRedis(count=4))  # type: ignore[arg-type]
    assert await limiter.allow(key="k", limit=3, window_seconds=60) is False

