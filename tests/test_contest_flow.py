"""Weekly contest end to end: admin switch → board in the bot → week end → prizes and reports."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from aiogram.methods import EditMessageText

from app.bot.scheduler import EngagementScheduler
from app.db.models import ReferralEdge, User
from app.services import contests, ledger
from tests.conftest import ADMIN_ID, OTHER_ID, USER_ID, BotHarness
from tests.fake_telegram import callback_update, message_update

pytestmark = pytest.mark.asyncio(loop_scope="module")

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)  # Wednesday of 2026-W41
WEEK = contests.week_of(NOW)


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def _clean_state(harness: BotHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    await harness.reset()
    monkeypatch.setattr(contests, "utc_now", lambda: NOW)


def _scheduler(h: BotHarness, moment: datetime) -> EngagementScheduler:
    return EngagementScheduler(h.bot, h.factory, h.store, h.notifier, clock=_at(moment))


def _at(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


async def _activate_friends(h: BotHarness, referrer_id: int, how_many: int, first_id: int) -> None:
    async with h.factory() as session:
        for offset in range(how_many):
            friend = User(id=first_id + offset, first_name="Friend", referral_activated=True)
            session.add(friend)
            await session.flush()
            activated_at = NOW + timedelta(minutes=offset + 1)
            session.add(
                ReferralEdge(referrer_id=referrer_id, referee_id=friend.id, level=1, credited_at=activated_at)
            )
        await session.commit()


def _buttons(h: BotHarness, chat_id: int) -> dict[str, str]:
    markup = [m for m in h.tg.sent(EditMessageText) if m.chat_id == chat_id][-1].reply_markup
    return {b.callback_data: b.text for row in markup.inline_keyboard for b in row if b.callback_data}


@pytest.mark.asyncio
async def test_board_appears_once_the_admin_switches_the_contest_on(harness: BotHarness) -> None:
    h = harness
    for user_id in (ADMIN_ID, USER_ID, OTHER_ID):
        await h.feed(message_update(user_id, "/start"))
    await h.feed(callback_update(USER_ID, "menu:top:contest"))
    assert "Топ по рефералам" in h.tg.last_text(USER_ID)
    assert "menu:top:contest" not in _buttons(h, USER_ID)

    await h.feed(callback_update(ADMIN_ID, "admin:set:contest_enabled:on"))
    await _activate_friends(h, USER_ID, 3, first_id=1000)
    await _activate_friends(h, OTHER_ID, 1, first_id=2000)

    await h.feed(callback_update(USER_ID, "menu:top:contest"))
    board = h.tg.last_text(USER_ID)
    assert "Конкурс недели" in board
    assert "@us***2 — <b>3</b> · 100" in board
    assert "@us***3 — <b>1</b>\n" in board  # below the minimum: no prize shown
    assert "Ты: <b>#1</b> · 3 друга — ты в призах" in board
    assert "Конкурс стартовал 07.10.2026 12:00 UTC" in board
    assert _buttons(h, USER_ID)["menu:top:contest"] == "• Конкурс недели"

    await h.feed(callback_update(OTHER_ID, "menu:top:contest"))
    assert "ещё 2 до призового минимума" in h.tg.last_text(OTHER_ID)

    await h.feed(callback_update(USER_ID, "menu:refs"))
    refs = h.tg.last_text(USER_ID)
    assert "Конкурс недели: до <b>100" in refs and "ты <b>#1</b> (3 друга)" in refs
    assert "menu:top:contest" in _buttons(h, USER_ID)

    await h.feed(callback_update(USER_ID, "menu:home"))
    assert "Конкурс недели: до <b>100" in h.tg.last_text(USER_ID)
    assert "menu:top:contest" in _buttons(h, USER_ID)

    await h.feed(callback_update(ADMIN_ID, "admin:set:contest_enabled:off"))
    await h.feed(callback_update(USER_ID, "menu:top:contest"))
    assert "Топ по рефералам" in h.tg.last_text(USER_ID)
    assert "menu:top:contest" not in _buttons(h, USER_ID)


@pytest.mark.asyncio
async def test_week_end_pays_the_winners_once_and_reports_to_admins(harness: BotHarness) -> None:
    h = harness
    for user_id in (ADMIN_ID, USER_ID, OTHER_ID):
        await h.feed(message_update(user_id, "/start"))
    await h.feed(callback_update(ADMIN_ID, "admin:set:contest_enabled:on"))
    await _activate_friends(h, USER_ID, 4, first_id=1000)
    await _activate_friends(h, OTHER_ID, 3, first_id=2000)
    async with h.factory() as session:
        balance_before = await ledger.get_balance(session, USER_ID)

    assert (await _scheduler(h, NOW).tick()).settled_weeks == ()
    assert (await _scheduler(h, WEEK.ends_at + timedelta(minutes=1)).tick()).settled_weeks == ()
    await h.feed(callback_update(ADMIN_ID, "admin:set:maintenance_mode:on"))
    assert (await _scheduler(h, WEEK.ends_at + contests.SETTLE_GRACE).tick()).settled_weeks == ()
    await h.feed(callback_update(ADMIN_ID, "admin:set:maintenance_mode:reset"))
    h.tg.clear()

    report = await _scheduler(h, WEEK.ends_at + timedelta(minutes=3)).tick()
    assert report.settled_weeks == (WEEK.key,)
    winner = h.tg.last_text(USER_ID)
    assert "Конкурс недели: 1 место!" in winner and "4 активных друга" in winner and "+100" in winner
    assert "Конкурс недели: 2 место!" in h.tg.last_text(OTHER_ID)
    summary = h.tg.last_text(ADMIN_ID)
    assert "Итоги конкурса" in summary and f"(<code>{USER_ID}</code>) — 4 реф." in summary
    assert "Начислено на балансы: <b>150" in summary
    async with h.factory() as session:
        assert await ledger.get_balance(session, USER_ID) == balance_before + 100

    h.tg.clear()
    assert (await _scheduler(h, WEEK.ends_at + timedelta(minutes=4)).tick()).settled_weeks == ()
    assert h.tg.texts() == []
