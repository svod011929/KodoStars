from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.txn import bind_session, unbind_session
from app.services import events

log = structlog.get_logger("kodostars.db")

EventDispatcher = Callable[[list[events.DomainEvent], dict[str, Any]], Awaitable[None]]


class DbSessionMiddleware(BaseMiddleware):
    """One session per update. Commits on success, rolls back on error and only
    then dispatches domain events collected during the handler.

    The session is also bound to a context variable so outbound network calls can
    commit pending work first (see :mod:`app.db.txn`). Because of that a handler
    may have committed several times before it returns; the final commit here just
    closes the last transaction.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._session_factory() as session:
            data["session"] = session
            token = bind_session(session)
            try:
                result = await handler(event, data)
                await session.commit()
            except Exception:
                await session.rollback()
                events.drain(session)
                raise
            finally:
                unbind_session(token)
            pending = events.drain(session)
        if pending and self._dispatcher is not None:
            try:
                await self._dispatcher(pending, data)
            except Exception:
                log.warning("event_dispatch_failed", exc_info=True)
        return result
