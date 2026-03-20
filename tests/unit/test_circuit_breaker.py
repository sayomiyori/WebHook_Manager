from __future__ import annotations

from unittest.mock import Mock
from uuid import uuid4

from src.infrastructure.queue.tasks.circuit_breaker import SyncCircuitBreaker


def test_circuit_breaker_record_failure_increments_and_sets_ttl() -> None:
    redis = Mock()
    redis.incr.return_value = 5
    redis.expire.return_value = True

    cb = SyncCircuitBreaker(redis=redis)  # type: ignore[arg-type]
    endpoint_id = str(uuid4())
    out = cb.record_failure(endpoint_id=endpoint_id, ttl_seconds=600)

    assert out == 5
    redis.incr.assert_called_once_with(f"cb:endpoint:{endpoint_id}")
    redis.expire.assert_called_once_with(f"cb:endpoint:{endpoint_id}", 600)


def test_circuit_breaker_reset_clears_key() -> None:
    redis = Mock()
    redis.delete.return_value = 1

    cb = SyncCircuitBreaker(redis=redis)  # type: ignore[arg-type]
    endpoint_id = str(uuid4())
    cb.reset(endpoint_id=endpoint_id)
    redis.delete.assert_called_once_with(f"cb:endpoint:{endpoint_id}")

