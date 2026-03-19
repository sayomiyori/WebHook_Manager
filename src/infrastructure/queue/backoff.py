from __future__ import annotations


def get_backoff_delay(attempt: int) -> int:
    """Returns seconds: [10, 30, 120, 600, 3600]."""
    delays = [10, 30, 120, 600, 3600]
    return delays[min(attempt, len(delays) - 1)]

