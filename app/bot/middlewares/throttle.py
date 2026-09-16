import contextlib
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.middlewares.events import unwrap_event


class ThrottleMiddleware(BaseMiddleware):
    """Per-user rate limit for messages and callbacks (LRU-bounded, in-memory).

    A burst of taps on the same button is answered silently instead of hitting
    the database and Telegram API several times.
    """

    def __init__(self, interval: float = 0.4, *, max_users: int = 20_000) -> None:
        self._interval = interval
        self._max_users = max_users
        self._last: OrderedDict[int, float] = OrderedDict()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self._interval <= 0:
            return await handler(event, data)
        inner = unwrap_event(event)
        if not isinstance(inner, (Message, CallbackQuery)) or inner.from_user is None:
            return await handler(event, data)
        if isinstance(inner, Message) and inner.successful_payment is not None:
            return await handler(event, data)

        user_id = inner.from_user.id
        now = time.monotonic()
        last = self._last.get(user_id)
        if last is not None and now - last < self._interval:
            if isinstance(inner, CallbackQuery):
                # Stop the client spinner; a stale/duplicate query is not an error.
                with contextlib.suppress(TelegramAPIError):
                    await inner.answer()
            return None
        self._remember(user_id, now)
        return await handler(event, data)

    def _remember(self, user_id: int, now: float) -> None:
        self._last[user_id] = now
        self._last.move_to_end(user_id)
        while len(self._last) > self._max_users:
            self._last.popitem(last=False)
