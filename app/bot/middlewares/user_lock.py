"""Serialise update processing per Telegram user.

aiogram handles updates concurrently. Two quick ``/start ref_…`` taps (or a
double-tap on «Вывод») therefore run two handlers on the same rows at once, and
every check-then-act pattern (``referred_by_id is None`` → insert edge,
``open_withdrawal() is None`` → create request …) becomes a race that ends in an
``IntegrityError`` or a duplicate. Holding one ``asyncio.Lock`` per user for the
duration of an update makes a user's actions strictly sequential while different
users still run in parallel.

``PreCheckoutQuery`` is exempt: it is read-only and Telegram expects an answer
within 10 seconds, so it must not queue behind a slow OP check.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import PreCheckoutQuery, TelegramObject

from app.bot.middlewares.events import unwrap_event


class UserLockMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._refs: dict[int, int] = {}

    @property
    def active_locks(self) -> int:
        return len(self._locks)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        inner = unwrap_event(event)
        user = getattr(inner, "from_user", None)
        if user is None or isinstance(inner, PreCheckoutQuery):
            return await handler(event, data)

        lock = self._locks.setdefault(user.id, asyncio.Lock())
        self._refs[user.id] = self._refs.get(user.id, 0) + 1
        try:
            async with lock:
                return await handler(event, data)
        finally:
            remaining = self._refs.get(user.id, 1) - 1
            if remaining <= 0:
                self._refs.pop(user.id, None)
                self._locks.pop(user.id, None)
            else:
                self._refs[user.id] = remaining
