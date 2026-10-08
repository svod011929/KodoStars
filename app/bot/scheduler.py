"""Jobs that run without an incoming update: the weekly contest and daily-claim reminders.

The loop ticks once a minute. Every tick reads the effective runtime settings, so
admins can change the reminder hour or switch a feature off without a restart.
Database work happens in short sessions that are committed before any message is
sent; Telegram I/O never runs inside a transaction. Jobs fail independently: a
broken one is logged, reported to the admins once, and retried on the next tick.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import partial
from typing import assert_never

import structlog
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import keyboards, texts
from app.bot.admin import texts as admin_texts
from app.bot.notify import Notifier
from app.config import Settings
from app.services import contests, daily, events, reminders
from app.services import users as user_service
from app.services.app_settings import RuntimeSettingsStore
from app.services.delivery import Delivery, deliver
from app.services.events import DomainEvent
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
    failed_jobs: list[str] = field(default_factory=list)


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
        self._failing: set[str] = set()

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
        settings = await self._settings()
        report = TickReport()
        if settings.maintenance_mode:
            return report
        failed = report.failed_jobs
        settled = await self._guarded("contest_settle", partial(self._settle_contests, now), failed)
        report.settled_weeks = settled or ()
        await self._guarded("contest_week", partial(self._sync_contest_week, now, settings), failed)
        if reminders.in_send_window(now, settings):
            run = await self._guarded("reminders", partial(self._send_reminders, now.date()), failed)
            report.reminders = run or ReminderRun()
        return report

    async def _settings(self) -> Settings:
        async with self._factory() as session:
            return await self._store.effective(session)

    async def _guarded[T](self, job: str, run: Callable[[], Awaitable[T]], failed: list[str]) -> T | None:
        """Run one job; a failure is logged and reported to the admins once per streak."""
        try:
            result = await run()
        except Exception:
            log.exception("engagement_job_failed", job=job)
            failed.append(job)
            if job not in self._failing:
                self._failing.add(job)
                alert = DomainEvent("admin_alert", {"text": admin_texts.scheduler_job_failed(job)})
                with contextlib.suppress(Exception):
                    await self._notifier.dispatch_events([alert])
            return None
        self._failing.discard(job)
        return result

    async def _settle_contests(self, now: datetime) -> tuple[str, ...]:
        async with self._factory() as session:
            settled = await contests.settle_due(session, now=now)
            await session.commit()
            pending = events.drain(session)
        for results in settled:
            log.info(
                "contest_settled",
                week=results.contest.week_key,
                winners=len(results.winners),
                paid=results.contest.paid_total,
            )
        if pending:
            await self._notifier.dispatch_events(pending)
        return tuple(results.contest.week_key for results in settled)

    async def _sync_contest_week(self, now: datetime, settings: Settings) -> None:
        async with self._factory() as session:
            await contests.sync_week(session, now=now, settings=settings)
            await session.commit()

    async def _send_reminders(self, today: date) -> ReminderRun:
        """Remind everyone due ``today``; stops as soon as the day or the send window ends.

        A run can take a while for a big audience, so the clock and the settings are
        re-read before every batch and the date before every message: a reminder is
        about today's claim and must not arrive after midnight.
        """
        run = ReminderRun()
        markup = keyboards.reminder_menu()
        after_id = 0
        while True:
            now = self._clock()
            settings = await self._settings()
            if (
                now.date() != today
                or settings.maintenance_mode
                or not reminders.in_send_window(now, settings)
            ):
                break
            outbox, cursor = await self._claim_batch(now, settings, after_id)
            if cursor is None:
                break
            after_id = cursor
            pause = 1.0 / max(settings.broadcast_rate_per_sec, 1)
            blocked: list[int] = []
            for user_id, text in outbox:
                if self._clock().date() != today:
                    break
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

    async def _claim_batch(
        self, now: datetime, settings: Settings, after_id: int
    ) -> tuple[list[tuple[int, str]], int | None]:
        today = now.date()
        async with self._factory() as session:
            batch = await reminders.claim_due(session, today=today, settings=settings, after_id=after_id)
            outbox = []
            for user in batch.users:
                preview = await daily.preview(session, user=user, settings=settings, now=now)
                outbox.append((user.id, texts.daily_reminder(preview, current_streak(user, today))))
            await session.commit()
        return outbox, batch.cursor
