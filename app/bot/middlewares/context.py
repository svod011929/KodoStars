from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.bot.middlewares.events import unwrap_event


class LoggingContextMiddleware(BaseMiddleware):
    """Bind ``update_id`` / ``user_id`` / ``event`` to structlog contextvars."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        inner = unwrap_event(event)
        user = getattr(inner, "from_user", None)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            update_id=event.update_id if isinstance(event, Update) else None,
            user_id=user.id if user is not None else None,
            event=type(inner).__name__,
        )
        try:
            return await handler(event, data)
        finally:
            structlog.contextvars.clear_contextvars()
