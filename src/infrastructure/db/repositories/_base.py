from __future__ import annotations

from uuid import UUID


def clamp_limit(limit: int, *, max_limit: int = 100) -> int:
    if limit <= 0:
        return 1
    if limit > max_limit:
        return max_limit
    return limit


def cursor_filter(model_id, cursor: UUID | None):  # type: ignore[no-untyped-def]
    if cursor is None:
        return None
    return model_id > cursor

