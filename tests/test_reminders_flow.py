"""Daily reminders end to end: scheduler tick → message → buttons → opt-out."""

from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from aiogram.methods import EditMessageText, SendMessage

from app.bot.scheduler import EngagementScheduler, ReminderRun
from app.db.models import User
from app.services import contests
from app.services.streaks import utc_today
from tests.conftest import ADMIN_ID, OTHER_ID, USER_ID, BotHarness
from tests.fake_telegram import callback_update, message_update

pytestmark = pytest.mark.asyncio(loop_scope="module")

THIRD_ID = 44


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def _clean_state(harness: BotHarness) -> None:
    await harness.reset()


def _scheduler(h: BotHarness, hour: int = 17) -> EngagementScheduler:
    at = datetime.now(UTC).replace(hour=hour, minute=5, second=0, microsecond=0)
    return EngagementScheduler(h.bot, h.factory, h.store, h.notifier, clock=lambda: at)


async def _remind(h: BotHarness, hour: int = 17) -> ReminderRun:
    return (await _scheduler(h, hour).tick()).reminders


async def _set(h: BotHarness, user_id: int, **values) -> None:
    async with h.factory() as session:
        user = await session.get(User, user_id)
        for key, value in values.items():
            setattr(user, key, value)
        await session.commit()


async def _user(h: BotHarness, user_id: int) -> User:
    async with h.factory() as session:
        return await session.get(User, user_id)


def _last_markup(h: BotHarness, user_id: int):
    return [m for m in h.tg.sent(SendMessage) if m.chat_id == user_id][-1].reply_markup


@pytest.mark.asyncio
async def test_reminder_is_sent_once_and_its_button_claims(harness: BotHarness) -> None:
    h = harness
    for user_id in (USER_ID, OTHER_ID, ADMIN_ID):
        await h.feed(message_update(user_id, "/start"))
    yesterday = utc_today() - timedelta(days=1)
    await _set(h, USER_ID, last_daily_on=yesterday, streak=3)
    await _set(h, OTHER_ID, last_daily_on=utc_today(), streak=1)
    h.tg.clear()

    assert (await _remind(h, hour=9)).sent == 0  # outside the send window
    run = await _remind(h)
    assert (run.sent, run.blocked, run.failed) == (1, 0, 0)
    reminder = h.tg.last_text(USER_ID)
    assert "Серия 3 дн. сгорит через" in reminder and "серия станет 4 дн." in reminder
    assert h.tg.texts(OTHER_ID) == [] and h.tg.texts(ADMIN_ID) == []
    buttons = [b.callback_data for row in _last_markup(h, USER_ID).inline_keyboard for b in row]
    assert buttons == ["daily:claim", "remind:off", "menu:home"]

    assert (await _remind(h)).sent == 0  # once per day

    await h.feed(callback_update(USER_ID, "daily:claim"))
    assert any("Серия: 4 дн. подряд" in text for text in h.tg.texts(USER_ID))


@pytest.mark.asyncio
async def test_opt_out_from_the_reminder_and_back_from_the_profile(harness: BotHarness) -> None:
    h = harness
    await h.feed(message_update(USER_ID, "/start"))
    await _set(h, USER_ID, last_daily_on=utc_today() - timedelta(days=2), streak=5)
    assert (await _remind(h)).sent == 1
    assert "Ежедневная награда ждёт" in h.tg.last_text(USER_ID)

    await h.feed(callback_update(USER_ID, "remind:off"))
    assert "выключены" in h.tg.last_text(USER_ID)
    assert (await _user(h, USER_ID)).reminders_enabled is False

    await h.feed(callback_update(USER_ID, "menu:profile"))
    profile_buttons = {b.callback_data: b.text for row in _last_edit_markup(h).inline_keyboard for b in row}
    assert profile_buttons["menu:remind:toggle"] == "Напоминания: выкл"
    await h.feed(callback_update(USER_ID, "menu:remind:toggle"))
    assert (await _user(h, USER_ID)).reminders_enabled is True
    profile_buttons = {b.callback_data: b.text for row in _last_edit_markup(h).inline_keyboard for b in row}
    assert profile_buttons["menu:remind:toggle"] == "Напоминания: вкл"


@pytest.mark.asyncio
async def test_blocked_users_are_marked_and_skipped(harness: BotHarness) -> None:
    h = harness
    for user_id in (USER_ID, THIRD_ID):
        await h.feed(message_update(user_id, "/start"))
        await _set(h, user_id, last_daily_on=utc_today() - timedelta(days=1), streak=2)
    h.tg.blocked_chats.add(THIRD_ID)
    run = await _remind(h)
    assert (run.sent, run.blocked) == (1, 1)
    assert (await _user(h, THIRD_ID)).blocked_bot_at is not None


@pytest.mark.asyncio
async def test_maintenance_and_runtime_switch_pause_reminders(harness: BotHarness) -> None:
    h = harness
    await h.feed(message_update(ADMIN_ID, "/start"))
    await h.feed(message_update(USER_ID, "/start"))
    await _set(h, USER_ID, last_daily_on=utc_today() - timedelta(days=1), streak=2)

    await h.feed(callback_update(ADMIN_ID, "admin:set:daily_reminder_enabled:off"))
    assert (await _remind(h)).sent == 0
    await h.feed(callback_update(ADMIN_ID, "admin:set:daily_reminder_enabled:reset"))
    await h.feed(callback_update(ADMIN_ID, "admin:set:maintenance_mode:on"))
    assert (await _remind(h)).sent == 0
    await h.feed(callback_update(ADMIN_ID, "admin:set:maintenance_mode:reset"))
    assert (await _remind(h)).sent == 1


@pytest.mark.asyncio
async def test_a_run_that_reaches_midnight_stops_sending(harness: BotHarness) -> None:
    h = harness
    for user_id in (USER_ID, THIRD_ID):
        await h.feed(message_update(user_id, "/start"))
        await _set(h, user_id, last_daily_on=utc_today() - timedelta(days=1), streak=2)
    async with h.factory() as session:
        await h.store.set(session, key="daily_reminder_hour_utc", raw="22", admin_id=ADMIN_ID)
        await session.commit()
    h.tg.clear()
    before = datetime.combine(utc_today(), time(23, 59, 58), tzinfo=UTC)

    def clock() -> datetime:
        # Midnight passes while the first reminder is on its way.
        return before + timedelta(seconds=3) if h.tg.sent(SendMessage) else before

    run = (await EngagementScheduler(h.bot, h.factory, h.store, h.notifier, clock=clock).tick()).reminders
    assert run.sent == 1 and h.tg.texts(THIRD_ID) == []
    assert "сгорит через 0 мин" in h.tg.last_text(USER_ID)

    next_evening = datetime.combine(utc_today() + timedelta(days=1), time(22, 5), tzinfo=UTC)
    scheduler = EngagementScheduler(h.bot, h.factory, h.store, h.notifier, clock=lambda: next_evening)
    assert (await scheduler.tick()).reminders.sent == 2


@pytest.mark.asyncio
async def test_a_broken_job_is_reported_once_and_does_not_stop_the_others(
    harness: BotHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    await h.feed(message_update(ADMIN_ID, "/start"))
    await h.feed(message_update(USER_ID, "/start"))
    await _set(h, USER_ID, last_daily_on=utc_today() - timedelta(days=1), streak=2)

    async def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(contests, "settle_due", broken)
    h.tg.clear()
    scheduler = _scheduler(h)
    report = await scheduler.tick()
    assert report.failed_jobs == ["contest_settle"] and report.reminders.sent == 1
    assert "«итоги конкурса недели» падает" in h.tg.last_text(ADMIN_ID)

    h.tg.clear()
    assert (await scheduler.tick()).failed_jobs == ["contest_settle"]
    assert h.tg.texts(ADMIN_ID) == []
    monkeypatch.undo()
    assert (await scheduler.tick()).failed_jobs == []
    monkeypatch.setattr(contests, "settle_due", broken)
    await scheduler.tick()
    assert "«итоги конкурса недели» падает" in h.tg.last_text(ADMIN_ID)


def _last_edit_markup(h: BotHarness):
    return [m for m in h.tg.sent(EditMessageText) if m.chat_id == USER_ID][-1].reply_markup
