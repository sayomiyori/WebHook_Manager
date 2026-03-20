from __future__ import annotations

from src.infrastructure.queue.backoff import get_backoff_delay


def test_backoff_exact_values() -> None:
    assert get_backoff_delay(0) == 10
    assert get_backoff_delay(1) == 30
    assert get_backoff_delay(2) == 120
    assert get_backoff_delay(3) == 600
    assert get_backoff_delay(4) == 3600


def test_backoff_greater_than_max_returns_last() -> None:
    assert get_backoff_delay(5) == 3600
    assert get_backoff_delay(999) == 3600

