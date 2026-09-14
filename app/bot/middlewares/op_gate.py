from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.config import Settings
from app.db.models import User
from app.op.base import OpContext
from app.op.gate import OpGate


_SKIP_PREFIXES = (
    "op:",
    "admin:",
)
_SKIP_COMMANDS = {"/admin", "/start"}


class OpGateMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings, gate: OpGate) -> None:
        self._settings = settings
        self._gate = gate

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if _should_skip(event, self._settings):
            return await handler(event, data)

        user: User | None = data.get("db_user")
        session: AsyncSession | None = data.get("session")
        bot: Bot | None = data.get("bot")
        if user is None or session is None:
            return await handler(event, data)
        if user.id in self._settings.admin_ids:
            return await handler(event, data)
        if user.is_banned:
            return await _reply(event, texts.banned(user.ban_reason or "бан"))
        if _op_fresh(user, self._settings.op_cache_sec):
            return await handler(event, data)

        ctx = OpContext(
            user_id=user.id,
            chat_id=_chat_id(event, user.id),
            first_name=user.first_name,
            username=user.username,
            language_code=user.language_code or "ru",
            is_premium=user.is_premium,
            bot=bot,
        )
        result = await self._gate.enforce(ctx, session)
        if result.allowed:
            user.last_op_ok_at = datetime.now(UTC)
            return await handler(event, data)

        markup = keyboards.op_keyboard(result.sponsors)
        await _reply(event, texts.op_blocked(result.provider, result.message), markup)
        if isinstance(event, CallbackQuery):
            await event.answer()
        return None


def _should_skip(event: TelegramObject, settings: Settings) -> bool:
    if isinstance(event, Message):
        text = (event.text or "").split(maxsplit=1)[0]
        if text in _SKIP_COMMANDS:
            return True
        if event.successful_payment is not None:
            return True
        return False
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return any(data.startswith(prefix) for prefix in _SKIP_PREFIXES)
    return True


def _op_fresh(user: User, cache_sec: int) -> bool:
    if not user.last_op_ok_at or cache_sec <= 0:
        return False
    last = user.last_op_ok_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return datetime.now(UTC) - last < timedelta(seconds=cache_sec)


def _chat_id(event: TelegramObject, fallback: int) -> int:
    if isinstance(event, Message) and event.chat:
        return event.chat.id
    if isinstance(event, CallbackQuery) and event.message and event.message.chat:
        return event.message.chat.id
    return fallback


async def _reply(event: TelegramObject, text: str, markup=None) -> None:
    if isinstance(event, Message):
        await event.answer(text, reply_markup=markup)
    elif isinstance(event, CallbackQuery) and event.message:
        await event.message.answer(text, reply_markup=markup)
