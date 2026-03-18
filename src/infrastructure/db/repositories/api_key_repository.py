from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.api_key import ApiKey
from src.domain.interfaces.repositories import ApiKeyRepository
from src.infrastructure.db.mappers import api_key_to_entity, api_key_to_model
from src.infrastructure.db.models.api_key import ApiKeyModel
from src.infrastructure.db.repositories._base import clamp_limit


class PostgresApiKeyRepository(ApiKeyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> ApiKey | None:
        model = await self._session.get(ApiKeyModel, id)
        return None if model is None else api_key_to_entity(model)

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[ApiKey]:
        lim = clamp_limit(limit)
        stmt = select(ApiKeyModel).where(ApiKeyModel.owner_id == owner_id)
        if cursor is not None:
            stmt = stmt.where(ApiKeyModel.id > cursor)
        stmt = stmt.order_by(ApiKeyModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [api_key_to_entity(m) for m in rows]

    async def get_by_prefix(self, owner_id: UUID, key_prefix: str) -> ApiKey | None:
        stmt = select(ApiKeyModel).where(
            ApiKeyModel.owner_id == owner_id, ApiKeyModel.key_prefix == key_prefix
        )
        model = (await self._session.execute(stmt)).scalars().first()
        return None if model is None else api_key_to_entity(model)

    async def create(self, api_key: ApiKey) -> ApiKey:
        model = api_key_to_model(api_key)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return api_key_to_entity(model)

    async def update(self, api_key: ApiKey) -> ApiKey:
        model = api_key_to_model(api_key)
        merged = await self._session.merge(model)
        await self._session.commit()
        await self._session.refresh(merged)
        return api_key_to_entity(merged)

    async def delete(self, id: UUID) -> None:
        await self._session.execute(delete(ApiKeyModel).where(ApiKeyModel.id == id))
        await self._session.commit()

