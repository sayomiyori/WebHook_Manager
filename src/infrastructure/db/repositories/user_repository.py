from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.user import User
from src.domain.interfaces.repositories import UserRepository
from src.infrastructure.db.mappers import user_to_entity, user_to_model
from src.infrastructure.db.models.user import UserModel


class PostgresUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> User | None:
        model = await self._session.get(UserModel, id)
        return None if model is None else user_to_entity(model)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(UserModel).where(UserModel.email == email)
        model = (await self._session.execute(stmt)).scalars().first()
        return None if model is None else user_to_entity(model)

    async def create(self, user: User) -> User:
        model = user_to_model(user)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return user_to_entity(model)

    async def update(self, user: User) -> User:
        model = user_to_model(user)
        merged = await self._session.merge(model)
        await self._session.commit()
        await self._session.refresh(merged)
        return user_to_entity(merged)

    async def delete(self, id: UUID) -> None:
        await self._session.execute(delete(UserModel).where(UserModel.id == id))
        await self._session.commit()

