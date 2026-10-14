from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.models.legacy_rate_limit import LegacyRateLimitModel


class RateLimiter:
    async def allow(self, *, key: str, limit: int, window_seconds: int = 60) -> bool:
        if limit <= 0:
            return False
        if window_seconds <= 0:
            raise ValueError("Rate-limit window must be positive")
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        model = LegacyRateLimitModel
        # Reclamation commits before admission locks, avoiding cross-key deadlocks.
        async with async_session_maker.begin() as session:
            expired = (
                select(model.key_hash)
                .where(model.expires_at <= func.statement_timestamp())
                .limit(100)
                .with_for_update(skip_locked=True)
            )
            await session.execute(delete(model).where(model.key_hash.in_(expired)))

        # Quota commits independently even when the HTTP request is rejected.
        async with async_session_maker.begin() as session:
            # The upsert locks an existing row before expiration can reclaim it.
            row = (
                await session.scalars(
                    insert(model)
                    .values(
                        key_hash=key_hash,
                        timestamps=[],
                        expires_at=func.clock_timestamp(),
                    )
                    .on_conflict_do_update(
                        index_elements=[model.key_hash], set_={"key_hash": key_hash}
                    )
                    .returning(model)
                )
            ).one()
            now: datetime = (
                await session.execute(select(func.clock_timestamp()))
            ).scalar_one()
            start = now - timedelta(seconds=window_seconds)
            timestamps = [stamp for stamp in row.timestamps if stamp > start]
            allowed = len(timestamps) < limit
            row.timestamps = (timestamps + [now])[-(limit + 1) :]
            row.expires_at = now + timedelta(seconds=window_seconds)
        return allowed
