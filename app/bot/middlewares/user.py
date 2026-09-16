from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    Message,
    PreCheckoutQuery,
    TelegramObject,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.middlewares.events import unwrap_event
from app.config import Settings
from app.services.users import upsert_user


class UserMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        inner = unwrap_event(event)
        if isinstance(inner, ChatMemberUpdated):
            # Block/unblock notifications are handled by their own handler.
            return await handler(event, data)
        tg_user = _extract_user(inner)
        session: AsyncSession | None = data.get("session")
        if tg_user is None or session is None or tg_user.is_bot:
            return await handler(event, data)
        settings: Settings = data.get("settings", self._settings)
        user, created = await upsert_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name or "",
            language_code=tg_user.language_code,
            is_premium=bool(tg_user.is_premium),
            settings=settings,
        )
        data["db_user"] = user
        data["user_created"] = created
        return await handler(event, data)


def _extract_user(inner: TelegramObject) -> Any | None:
    if isinstance(inner, (Message, CallbackQuery, PreCheckoutQuery)):
        return inner.from_user
    return getattr(inner, "from_user", None)
