from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import User
from app.services import reminders
from app.services.streaks import utc_today


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime.now(UTC).replace(hour=hour, minute=minute, second=0, microsecond=0)


def test_send_window_follows_the_configured_hour(settings) -> None:
    settings.daily_reminder_hour_utc = 17
    assert not reminders.in_send_window(_at(16, 59), settings)
    assert reminders.in_send_window(_at(17), settings)
    assert reminders.in_send_window(_at(19, 59), settings)
    assert not reminders.in_send_window(_at(20), settings)
    settings.daily_reminder_enabled = False
    assert not reminders.in_send_window(_at(17), settings)


@pytest.mark.asyncio
async def test_claim_due_picks_each_user_once_per_day(session, settings) -> None:
    settings.daily_reminder_window_days = 3
    today = utc_today()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    long_ago = day_start - timedelta(days=30)

    def user(user_id: int, *, claimed_days_ago: int | None, started: datetime = long_ago, **extra) -> User:
        last = today - timedelta(days=claimed_days_ago) if claimed_days_ago is not None else None
        return User(id=user_id, first_name=f"U{user_id}", last_daily_on=last, started_at=started, **extra)

    session.add_all(
        [
            user(1, claimed_days_ago=1, streak=4),  # streak about to lapse
            user(2, claimed_days_ago=0),  # already claimed today
            user(3, claimed_days_ago=3),  # lapsed, still inside the window
            user(4, claimed_days_ago=4),  # gone quiet: leave alone
            user(5, claimed_days_ago=None, started=day_start - timedelta(hours=5)),  # joined yesterday
            user(6, claimed_days_ago=None, started=day_start + timedelta(minutes=1)),  # joined today
            user(7, claimed_days_ago=None, started=day_start - timedelta(days=5)),  # never came back
            user(8, claimed_days_ago=1, reminders_enabled=False),
            user(9, claimed_days_ago=1, is_banned=True),
            user(10, claimed_days_ago=1, blocked_bot_at=long_ago),
            user(11, claimed_days_ago=1, last_reminded_on=today),
            user(12, claimed_days_ago=1, last_reminded_on=today - timedelta(days=1)),
        ]
    )
    await session.flush()

    due = await reminders.claim_due(session, today=today, settings=settings)
    assert [u.id for u in due] == [1, 3, 5, 12]
    assert all(u.last_reminded_on == today for u in due)
    assert await reminders.claim_due(session, today=today, settings=settings) == []


@pytest.mark.asyncio
async def test_claim_due_respects_the_batch_limit(session, settings) -> None:
    yesterday = utc_today() - timedelta(days=1)
    session.add_all([User(id=i, first_name="U", last_daily_on=yesterday) for i in range(1, 6)])
    await session.flush()
    first = await reminders.claim_due(session, today=utc_today(), settings=settings, limit=2)
    rest = await reminders.claim_due(session, today=utc_today(), settings=settings, limit=10)
    assert [u.id for u in first] == [1, 2]
    assert [u.id for u in rest] == [3, 4, 5]
