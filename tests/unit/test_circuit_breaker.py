from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.infrastructure.queue.tasks.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_circuit_breaker_record_failure_increments_and_sets_ttl() -> None:
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=5)
    redis.expire = AsyncMock(return_value=True)

    cb = CircuitBreaker(redis=redis)  # type: ignore[arg-type]
    out = await cb.record_failure(endpoint_id=str(uuid4()), ttl_seconds=600)

    assert out == 5
    redis.incr.assert_awaited_once()
    redis.expire.assert_awaited_once()


@pytest.mark.asyncio
async def test_circuit_breaker_reset_deletes_key() -> None:
    redis = AsyncMock()
    redis.delete = AsyncMock(return_value=1)

    cb = CircuitBreaker(redis=redis)  # type: ignore[arg-type]
    endpoint_id = str(uuid4())
    await cb.reset(endpoint_id=endpoint_id)
    redis.delete.assert_awaited_once()

