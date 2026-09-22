from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import brand
from app.bot import emoji as pe
from app.bot.middlewares.events import unwrap_event
from app.services.access import AccessRegistry
from app.services.app_settings import RuntimeSettingsStore


class RuntimeMiddleware(BaseMiddleware):
    """Inject effective settings (env + DB overrides), admin flag and maintenance gate."""

    def __init__(self, store: RuntimeSettingsStore, access: AccessRegistry) -> None:
        self._store = store
        self._access = access
        pe.apply_currency(store.base.currency_emoji_id, store.base.currency_emoji_fallback)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        data["access"] = self._access
        data["settings_store"] = self._store
        if session is not None:
            if not self._access.loaded:
                await self._access.load(session)
            data["settings"] = await self._store.effective(session)
        else:
            data["settings"] = self._store.base

        inner = unwrap_event(event)
        user = getattr(inner, "from_user", None)
        is_admin = user is not None and self._access.is_admin(user.id)
        data["is_admin"] = is_admin

        settings = data["settings"]
        if settings.maintenance_mode and not is_admin:
            notice = brand.expand(settings.maintenance_text) or settings.maintenance_text
            if isinstance(inner, Message):
                await inner.answer(notice)
                return None
            if isinstance(inner, CallbackQuery):
                await inner.answer(notice[:190], show_alert=True)
                return None
        return await handler(event, data)
