from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, TelegramObject
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
        tg_user = _extract_user(event)
        session: AsyncSession | None = data.get("session")
        if tg_user is None or session is None:
            return await handler(event, data)
        user, created = await upsert_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name or "",
            language_code=tg_user.language_code,
            is_premium=bool(tg_user.is_premium),
            settings=self._settings,
        )
        data["db_user"] = user
        data["user_created"] = created
        return await handler(event, data)


def _extract_user(event: TelegramObject) -> Any | None:
    inner = unwrap_event(event)
    if isinstance(inner, (Message, CallbackQuery, PreCheckoutQuery)):
        return inner.from_user
    return getattr(inner, "from_user", None)
