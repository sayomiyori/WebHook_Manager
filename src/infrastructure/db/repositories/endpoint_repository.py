from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.domain.entities.endpoint import Endpoint
from src.domain.interfaces.repositories import EndpointRepository
from src.infrastructure.db.mappers import endpoint_to_entity, endpoint_to_model
from src.infrastructure.db.models.endpoint import EndpointModel
from src.infrastructure.db.repositories._base import clamp_limit


class PostgresEndpointRepository(EndpointRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> Endpoint | None:
        model = await self._session.get(EndpointModel, id)
        return None if model is None else endpoint_to_entity(model)

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Endpoint]:
        lim = clamp_limit(limit)
        stmt = select(EndpointModel).where(EndpointModel.owner_id == owner_id)
        if cursor is not None:
            stmt = stmt.where(EndpointModel.id > cursor)
        stmt = stmt.order_by(EndpointModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [endpoint_to_entity(m) for m in rows]

    async def create(self, endpoint: Endpoint) -> Endpoint:
        model = endpoint_to_model(endpoint)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return endpoint_to_entity(model)

    async def update(self, endpoint: Endpoint) -> Endpoint:
        model = await self._session.get(
            EndpointModel, endpoint.id, with_for_update=True, populate_existing=True
        )
        if model is None:
            raise NotFoundError()
        # Configuration edits cannot overwrite the independently updated counter.
        model.name, model.url, model.secret = (
            endpoint.name,
            endpoint.url,
            endpoint.secret,
        )
        model.is_active, model.updated_at = endpoint.is_active, endpoint.updated_at
        await self._session.flush()
        await self._session.refresh(model)
        result = endpoint_to_entity(model)
        await self._session.commit()
        return result

    async def update_failure_count(self, id: UUID, *, reset: bool = False) -> Endpoint:
        model = await self._session.scalar(
            update(EndpointModel)
            .where(EndpointModel.id == id)
            .values(
                failure_count=0 if reset else EndpointModel.failure_count + 1,
                updated_at=func.clock_timestamp(),
            )
            .returning(EndpointModel)
            .execution_options(populate_existing=True)
        )
        if model is None:
            raise NotFoundError()
        result = endpoint_to_entity(model)
        await self._session.commit()
        return result

    async def delete(self, id: UUID) -> None:
        await self._session.execute(delete(EndpointModel).where(EndpointModel.id == id))
        await self._session.commit()
