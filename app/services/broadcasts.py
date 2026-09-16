"""Background broadcast runner.

A broadcast is a stored reference to the admin's message (``copy_message`` keeps
formatting and media) plus an optional URL button. The runner walks the audience
with pacing below Telegram's global limit, persists progress periodically and
supports cooperative cancellation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import structlog
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Broadcast, BroadcastAudience, BroadcastStatus, User
from app.services import users as user_service
from app.services.errors import NotFound, ValidationError

log = structlog.get_logger("kodostars.broadcast")

# (broadcast, chat_id, message_id) → edit the progress card the admin is watching.
ProgressCallback = Callable[[Broadcast, int, int], Awaitable[None]]


class Sender(Protocol):
    async def __call__(self, chat_id: int, broadcast: Broadcast) -> None: ...


@dataclass(slots=True)
class SendOutcome:
    sent: int = 0
    failed: int = 0
    blocked: int = 0


async def create_broadcast(
    session: AsyncSession,
    *,
    admin_id: int,
    from_chat_id: int,
    message_id: int,
    audience: str,
    button_text: str | None = None,
    button_url: str | None = None,
) -> Broadcast:
    if audience not in {item.value for item in BroadcastAudience}:
        raise ValidationError("Неизвестная аудитория")
    if bool(button_text) != bool(button_url):
        raise ValidationError("Для кнопки нужны и текст, и ссылка")
    if button_url and not button_url.startswith(("http://", "https://", "tg://")):
        raise ValidationError("Ссылка кнопки должна начинаться с https://")
    ids = await user_service.audience_ids(session, audience)
    row = Broadcast(
        admin_id=admin_id,
        from_chat_id=from_chat_id,
        message_id=message_id,
        audience=audience,
        button_text=(button_text or "")[:64] or None,
        button_url=(button_url or "")[:512] or None,
        status=BroadcastStatus.PENDING.value,
        total=len(ids),
    )
    session.add(row)
    await session.flush()
    return row


async def get_broadcast(session: AsyncSession, broadcast_id: int) -> Broadcast:
    row = await session.get(Broadcast, broadcast_id)
    if row is None:
        raise NotFound("Рассылка не найдена")
    return row


async def list_broadcasts(session: AsyncSession, *, limit: int = 10) -> list[Broadcast]:
    result = await session.execute(select(Broadcast).order_by(Broadcast.id.desc()).limit(limit))
    return list(result.scalars().all())


async def running_broadcast(session: AsyncSession) -> Broadcast | None:
    result = await session.execute(
        select(Broadcast)
        .where(Broadcast.status == BroadcastStatus.RUNNING.value)
        .order_by(Broadcast.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def audience_size(session: AsyncSession, audience: str) -> int:
    return len(await user_service.audience_ids(session, audience))


class BroadcastRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        sender: Sender,
        rate_per_sec: int = 20,
        progress_every: int = 25,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._factory = session_factory
        self._sender = sender
        self._interval = 1.0 / max(rate_per_sec, 1)
        self._progress_every = max(progress_every, 1)
        self._progress_callback = progress_callback
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._cancelled: set[int] = set()
        self._watchers: dict[int, tuple[int, int]] = {}

    def watch(self, broadcast_id: int, chat_id: int, message_id: int) -> None:
        """Remember the admin's progress card so the runner can keep it updated."""
        self._watchers[broadcast_id] = (chat_id, message_id)

    def is_running(self, broadcast_id: int) -> bool:
        task = self._tasks.get(broadcast_id)
        return task is not None and not task.done()

    def cancel(self, broadcast_id: int) -> bool:
        if not self.is_running(broadcast_id):
            return False
        self._cancelled.add(broadcast_id)
        return True

    def start(self, broadcast_id: int) -> asyncio.Task[None]:
        if self.is_running(broadcast_id):
            return self._tasks[broadcast_id]
        task = asyncio.create_task(self.run(broadcast_id), name=f"broadcast-{broadcast_id}")
        self._tasks[broadcast_id] = task
        return task

    async def shutdown(self) -> None:
        for broadcast_id in list(self._tasks):
            self.cancel(broadcast_id)
        pending = [task for task in self._tasks.values() if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def run(self, broadcast_id: int) -> None:
        async with self._factory() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is None:
                return
            ids = await user_service.audience_ids(session, broadcast.audience)
            broadcast.total = len(ids)
            broadcast.status = BroadcastStatus.RUNNING.value
            broadcast.started_at = datetime.now(UTC)
            await session.commit()

        outcome = SendOutcome()
        blocked_ids: list[int] = []
        final_status = BroadcastStatus.DONE.value
        error: str | None = None
        try:
            for index, chat_id in enumerate(ids, start=1):
                if broadcast_id in self._cancelled:
                    final_status = BroadcastStatus.CANCELLED.value
                    break
                await self._send_one(chat_id, broadcast, outcome, blocked_ids)
                if index % self._progress_every == 0:
                    await self._persist(broadcast_id, outcome, blocked_ids, status=None)
                    blocked_ids.clear()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            final_status = BroadcastStatus.CANCELLED.value
            raise
        except Exception as exc:  # pragma: no cover - defensive
            final_status = BroadcastStatus.FAILED.value
            error = str(exc)[:500]
            log.exception("broadcast_failed", broadcast_id=broadcast_id)
        finally:
            await self._persist(broadcast_id, outcome, blocked_ids, status=final_status, error=error)
            self._cancelled.discard(broadcast_id)
            self._tasks.pop(broadcast_id, None)

    async def _send_one(
        self,
        chat_id: int,
        broadcast: Broadcast,
        outcome: SendOutcome,
        blocked_ids: list[int],
    ) -> None:
        for _attempt in range(3):
            try:
                await self._sender(chat_id, broadcast)
                outcome.sent += 1
                return
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 0.5)
                continue
            except TelegramForbiddenError:
                outcome.blocked += 1
                blocked_ids.append(chat_id)
                return
            except TelegramNotFound:
                outcome.blocked += 1
                blocked_ids.append(chat_id)
                return
            except TelegramBadRequest as exc:
                message = str(exc).lower()
                if "chat not found" in message or "deactivated" in message:
                    outcome.blocked += 1
                    blocked_ids.append(chat_id)
                else:
                    outcome.failed += 1
                return
            except Exception:
                log.warning("broadcast_send_error", chat_id=chat_id, exc_info=True)
                outcome.failed += 1
                return
        outcome.failed += 1

    async def _persist(
        self,
        broadcast_id: int,
        outcome: SendOutcome,
        blocked_ids: list[int],
        *,
        status: str | None,
        error: str | None = None,
    ) -> None:
        async with self._factory() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is None:
                return
            broadcast.sent = outcome.sent
            broadcast.failed = outcome.failed
            broadcast.blocked = outcome.blocked
            if status is not None:
                broadcast.status = status
                broadcast.finished_at = datetime.now(UTC)
                broadcast.error = error
            now = datetime.now(UTC)
            for uid in blocked_ids:
                user = await session.get(User, uid)
                if user is not None and user.blocked_bot_at is None:
                    user.blocked_bot_at = now
            await session.commit()
            snapshot = broadcast
        watcher = self._watchers.get(broadcast_id)
        if self._progress_callback is not None and watcher is not None:
            try:
                await self._progress_callback(snapshot, *watcher)
            except Exception:
                log.warning("broadcast_progress_callback_failed", exc_info=True)
        if status is not None:
            self._watchers.pop(broadcast_id, None)
