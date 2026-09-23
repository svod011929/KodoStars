from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.middlewares.events import unwrap_event
from app.config import Settings
from app.db.models import User
from app.op.base import OpContext, OpResult
from app.op.gate import OpGate

_SKIP_PREFIXES = (
    "op:",
    "admin:",
    "noop",
)
_SKIP_COMMANDS = {"/admin", "/start", "/help", "/paysupport", "/terms"}


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
        settings: Settings = data.get("settings", self._settings)
        if _should_skip(event, settings):
            return await handler(event, data)

        user: User | None = data.get("db_user")
        session: AsyncSession | None = data.get("session")
        bot: Bot | None = data.get("bot")
        if user is None or session is None:
            return await handler(event, data)
        if data.get("is_admin") or user.id in settings.admin_ids:
            return await handler(event, data)
        inner = unwrap_event(event)
        if user.is_banned:
            if isinstance(inner, CallbackQuery):
                await inner.answer(texts.banned_short(), show_alert=True)
                return None
            return await _reply(inner, texts.banned(user.ban_reason or "бан", settings.support_contact))
        if _op_fresh(user, settings.op_cache_sec):
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
        # Verified → PiarFlow then Tgrass; unverified → Tgrass only (no hard device gate).
        result = await self._gate.enforce(ctx, session, settings=settings, user=user)
        if not result.allowed:
            await _reply_blocked(inner, result, l1_bonus=settings.referral_l1_bonus)
            return None

        user.last_op_ok_at = datetime.now(UTC)
        return await handler(event, data)


def _should_skip(event: TelegramObject, settings: Settings) -> bool:
    event = unwrap_event(event)
    if isinstance(event, Message):
        if event.successful_payment is not None:
            return True
        parts = (event.text or "").split(maxsplit=1)
        command = parts[0] if parts else ""
        return command in _SKIP_COMMANDS
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
    event = unwrap_event(event)
    if isinstance(event, Message) and event.chat:
        return event.chat.id
    if isinstance(event, CallbackQuery) and event.message and event.message.chat:
        return event.message.chat.id
    return fallback


async def _reply_blocked(event: TelegramObject, result: OpResult, *, l1_bonus: int = 0) -> None:
    inner = unwrap_event(event)
    markup = keyboards.op_keyboard(result.sponsors)
    await _reply(
        inner,
        texts.op_blocked(result.provider, result.message, l1_bonus=l1_bonus),
        markup,
    )
    if isinstance(inner, CallbackQuery):
        await inner.answer()


async def _reply(event: TelegramObject, text: str, markup=None) -> None:
    event = unwrap_event(event)
    if isinstance(event, Message):
        await event.answer(text, reply_markup=markup)
    elif isinstance(event, CallbackQuery) and event.message:
        await event.message.answer(text, reply_markup=markup)
