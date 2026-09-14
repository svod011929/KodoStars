from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import Base


def create_engine(settings: Settings, *, echo: bool = False) -> AsyncEngine:
    if settings.is_sqlite:
        if ":memory:" in settings.database_url or settings.database_url.endswith("://"):
            return create_async_engine(
                settings.database_url,
                echo=echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        db_path = settings.database_url.split("///", maxsplit=1)[-1]
        if db_path.startswith("./"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(settings.database_url, echo=echo)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
