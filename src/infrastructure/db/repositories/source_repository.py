from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.source import Source
from src.domain.interfaces.repositories import SourceRepository
from src.infrastructure.db.mappers import source_to_entity, source_to_model
from src.infrastructure.db.models.source import SourceModel
from src.infrastructure.db.repositories._base import clamp_limit


class PostgresSourceRepository(SourceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> Source | None:
        model = await self._session.get(SourceModel, id)
        return None if model is None else source_to_entity(model)

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Source]:
        lim = clamp_limit(limit)
        stmt = select(SourceModel).where(SourceModel.owner_id == owner_id)
        if cursor is not None:
            stmt = stmt.where(SourceModel.id > cursor)
        stmt = stmt.order_by(SourceModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [source_to_entity(m) for m in rows]

    async def get_by_slug(self, owner_id: UUID, slug: str) -> Source | None:
        stmt = select(SourceModel).where(
            SourceModel.owner_id == owner_id, SourceModel.slug == slug
        )
        model = (await self._session.execute(stmt)).scalars().first()
        return None if model is None else source_to_entity(model)

    async def create(self, source: Source) -> Source:
        model = source_to_model(source)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return source_to_entity(model)

    async def update(self, source: Source) -> Source:
        model = source_to_model(source)
        merged = await self._session.merge(model)
        await self._session.commit()
        await self._session.refresh(merged)
        return source_to_entity(merged)

    async def delete(self, id: UUID) -> None:
        await self._session.execute(delete(SourceModel).where(SourceModel.id == id))
        await self._session.commit()

