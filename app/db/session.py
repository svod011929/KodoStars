from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import Base

SQLITE_BUSY_TIMEOUT_MS = 15_000


def create_engine(
    settings: Settings, *, echo: bool = False, busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS
) -> AsyncEngine:
    if settings.is_sqlite:
        if ":memory:" in settings.database_url or settings.database_url.endswith("://"):
            engine = create_async_engine(
                settings.database_url,
                echo=echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            db_path = settings.database_url.split("///", maxsplit=1)[-1]
            if db_path.startswith("./") or not Path(db_path).is_absolute():
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            engine = create_async_engine(settings.database_url, echo=echo)
        _tune_sqlite(engine, busy_timeout_ms=busy_timeout_ms)
        return engine
    return create_async_engine(settings.database_url, echo=echo, pool_pre_ping=True)


def _tune_sqlite(engine: AsyncEngine, *, busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS) -> None:
    """WAL + busy timeout: lets the polling loop and background workers share one file.

    Transactions never span network I/O (see :mod:`app.db.txn`), so write locks are
    held for milliseconds; the generous busy timeout only covers rare long writers
    such as a big broadcast progress flush.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:  # pragma: no cover - driver glue
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables directly. Used by tests; production runs Alembic (app.db.migrate)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
