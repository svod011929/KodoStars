"""One bulk-message delivery attempt with Telegram's flood control and dead-chat handling."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum

import structlog
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)

log = structlog.get_logger("kodostars.delivery")


class Delivery(StrEnum):
    SENT = "sent"
    BLOCKED = "blocked"  # the user blocked the bot or the chat no longer exists
    FAILED = "failed"


async def deliver(send: Callable[[], Awaitable[object]], *, chat_id: int, attempts: int = 3) -> Delivery:
    for _attempt in range(attempts):
        try:
            await send()
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 0.5)
            continue
        except (TelegramForbiddenError, TelegramNotFound):
            return Delivery.BLOCKED
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            if "chat not found" in message or "deactivated" in message:
                return Delivery.BLOCKED
            return Delivery.FAILED
        except Exception:
            log.warning("delivery_error", chat_id=chat_id, exc_info=True)
            return Delivery.FAILED
        return Delivery.SENT
    return Delivery.FAILED
