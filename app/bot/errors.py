"""Global error handling: log, tell the user something sane, alert owners."""

from __future__ import annotations

import time
import traceback

import structlog
from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app.bot.utils import h
from app.services.access import AccessRegistry
from app.services.errors import EconomyError

log = structlog.get_logger("kodostars.errors")
router = Router(name="errors")

_ALERT_COOLDOWN_SEC = 60.0
_last_alert: dict[str, float] = {}


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot, access: AccessRegistry | None = None) -> bool:
    exc = event.exception
    update = event.update
    inner = update.message or update.callback_query

    if isinstance(exc, EconomyError):
        await _reply(inner, f"⚠️ {h(exc.message)}")
        return True

    if isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc).lower():
        return True

    log.error(
        "handler_error",
        update_id=update.update_id,
        error=repr(exc),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    await _reply(inner, "😕 Что-то пошло не так. Попробуйте ещё раз или откройте /menu.")
    if access is not None and not isinstance(exc, TelegramAPIError):
        await _alert_owners(bot, access, exc, update.update_id)
    return True


async def _reply(inner: Message | CallbackQuery | None, text: str) -> None:
    try:
        if isinstance(inner, CallbackQuery):
            await inner.answer(text[:190], show_alert=True)
        elif isinstance(inner, Message):
            await inner.answer(text)
    except TelegramAPIError:
        pass


async def _alert_owners(bot: Bot, access: AccessRegistry, exc: BaseException, update_id: int) -> None:
    key = type(exc).__name__
    now = time.monotonic()
    if now - _last_alert.get(key, 0.0) < _ALERT_COOLDOWN_SEC:
        return
    _last_alert[key] = now
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
    text = f"🚨 <b>Ошибка в боте</b> (update {update_id})\n<pre>{h(tb)}</pre>"
    for owner_id in access.owners:
        try:
            await bot.send_message(owner_id, text)
        except TelegramAPIError:
            continue
