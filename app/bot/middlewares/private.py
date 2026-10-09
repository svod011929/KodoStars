import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Chat, Message, TelegramObject

from app.bot.middlewares.events import unwrap_event


class PrivateChatMiddleware(BaseMiddleware):
    """Drop messages and button taps from groups and channels before any work.

    The bot is an admin in ambassadors' chats (promo auto-posts), so it receives
    every message there. Handling them would register the members with a signup
    bonus, spend their first ``/start`` (losing the referral they open later) and
    post screens or the sponsor wall into the chat.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        inner = unwrap_event(event)
        chat = _chat(inner)
        if chat is None or chat.type == ChatType.PRIVATE:
            return await handler(event, data)
        if isinstance(inner, CallbackQuery):
            with contextlib.suppress(TelegramAPIError):
                await inner.answer()
        return None


def _chat(event: TelegramObject) -> Chat | None:
    if isinstance(event, Message):
        return event.chat
    if isinstance(event, CallbackQuery) and event.message is not None:
        return event.message.chat
    return None
