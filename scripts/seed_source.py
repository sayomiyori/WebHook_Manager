from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from src.domain.entities.source import Source
from src.domain.entities.user import User
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.repositories.source_repository import PostgresSourceRepository
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository


async def main() -> None:
    slug = "stripe"
    now = datetime.now(UTC)
    async with async_session_maker() as session:
        user_repo = PostgresUserRepository(session)
        repo = PostgresSourceRepository(session)
        existing = await repo.get_by_slug_global(slug)
        if existing is not None:
            print(f"exists slug={slug} id={existing.id}")
            return
        user = User(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            email=f"seed-{uuid4()}@example.com",
            hashed_password="seed",
            is_active=True,
        )
        await user_repo.create(user)
        src = Source(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="Stripe",
            slug=slug,
            owner_id=user.id,
            secret=None,
            is_active=True,
        )
        await repo.create(src)
        print(f"created slug={slug} id={src.id}")


if __name__ == "__main__":
    asyncio.run(main())

