"""Jobs that run without an incoming update: the weekly contest and daily-claim reminders.

The loop ticks once a minute. Every tick reads the effective runtime settings, so
admins can change the reminder hour or switch a feature off without a restart.
Database work happens in short sessions that are committed before any message is
sent; Telegram I/O never runs inside a transaction.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import partial
from typing import assert_never

import structlog
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import keyboards, texts
from app.bot.notify import Notifier
from app.config import Settings
from app.services import contests, daily, events, reminders
from app.services import users as user_service
from app.services.app_settings import RuntimeSettingsStore
from app.services.delivery import Delivery, deliver
from app.services.streaks import current_streak

log = structlog.get_logger("kodostars.scheduler")

TICK_SECONDS = 60.0


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class ReminderRun:
    sent: int = 0
    blocked: int = 0
    failed: int = 0


@dataclass(slots=True)
class TickReport:
    settled_weeks: tuple[str, ...] = ()
    reminders: ReminderRun = field(default_factory=ReminderRun)


class EngagementScheduler:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings_store: RuntimeSettingsStore,
        notifier: Notifier,
        *,
        clock: Callable[[], datetime] = utc_now,
        interval: float = TICK_SECONDS,
    ) -> None:
        self._bot = bot
        self._factory = session_factory
        self._store = settings_store
        self._notifier = notifier
        self._clock = clock
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="engagement-scheduler")

    async def shutdown(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("engagement_tick_failed")
            await asyncio.sleep(self._interval)

    async def tick(self) -> TickReport:
        now = self._clock()
        async with self._factory() as session:
            settings = await self._store.effective(session)
        report = TickReport()
        if settings.maintenance_mode:
            return report
        report.settled_weeks = await self._run_contest(now, settings)
        if reminders.in_send_window(now, settings):
            report.reminders = await self._send_reminders(now.date(), settings)
        return report

    async def _run_contest(self, now: datetime, settings: Settings) -> tuple[str, ...]:
        async with self._factory() as session:
            settled = await contests.settle_due(session, now=now, settings=settings)
            await contests.open_week(session, now=now, settings=settings)
            await session.commit()
            pending = events.drain(session)
        for results in settled:
            log.info(
                "contest_settled",
                week=results.contest.week_key,
                status=results.contest.status,
                winners=len(results.winners),
                paid=results.contest.paid_total,
            )
        if pending:
            await self._notifier.dispatch_events(pending)
        return tuple(results.contest.week_key for results in settled)

    async def _send_reminders(self, today: date, settings: Settings) -> ReminderRun:
        run = ReminderRun()
        pause = 1.0 / max(settings.broadcast_rate_per_sec, 1)
        markup = keyboards.reminder_menu()
        while outbox := await self._claim_batch(today, settings):
            blocked: list[int] = []
            for user_id, text in outbox:
                send = partial(self._bot.send_message, user_id, text, reply_markup=markup)
                result = await deliver(send, chat_id=user_id)
                match result:
                    case Delivery.SENT:
                        run.sent += 1
                    case Delivery.BLOCKED:
                        run.blocked += 1
                        blocked.append(user_id)
                    case Delivery.FAILED:
                        run.failed += 1
                    case _:
                        assert_never(result)
                await asyncio.sleep(pause)
            if blocked:
                async with self._factory() as session:
                    await user_service.mark_blocked(session, blocked)
                    await session.commit()
        if run.sent or run.blocked or run.failed:
            log.info("daily_reminders_sent", sent=run.sent, blocked=run.blocked, failed=run.failed)
        return run

    async def _claim_batch(self, today: date, settings: Settings) -> list[tuple[int, str]]:
        async with self._factory() as session:
            due = await reminders.claim_due(session, today=today, settings=settings)
            outbox = []
            for user in due:
                preview = await daily.preview(session, user=user, settings=settings)
                outbox.append((user.id, texts.daily_reminder(preview, current_streak(user, today))))
            await session.commit()
        return outbox
