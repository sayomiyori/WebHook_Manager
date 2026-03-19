from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.core.config import settings


class Base(DeclarativeBase):
    pass


engine: AsyncEngine = create_async_engine(
    str(settings.DATABASE_URL),
    pool_pre_ping=True,
)

_sync_db_url = str(settings.DATABASE_URL).replace(
    "postgresql+asyncpg",
    "postgresql+psycopg",
)
sync_engine = create_engine(
    _sync_db_url,
    pool_pre_ping=True,
)
sync_session_maker = sessionmaker(bind=sync_engine, expire_on_commit=False)

async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def check_db_health() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

