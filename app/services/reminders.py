"""Daily-claim reminders: who is due today, at most one reminder per user per UTC day."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User

BATCH_SIZE = 100
# Reminders keep going out for a few hours after the configured one, so a restart
# shortly after it still delivers them, but nobody gets one in the middle of the night.
SEND_WINDOW_HOURS = 3


def in_send_window(now: datetime, settings: Settings) -> bool:
    if not settings.daily_reminder_enabled:
        return False
    return 0 <= now.hour - settings.daily_reminder_hour_utc < SEND_WINDOW_HOURS


async def claim_due(
    session: AsyncSession, *, today: date, settings: Settings, limit: int = BATCH_SIZE
) -> list[User]:
    """Next users to remind today, already marked as reminded.

    Users qualify when they have not claimed today and either claimed within the
    last ``daily_reminder_window_days`` days or started the bot within that window
    without ever claiming. They are marked before anything is sent, so a crash or
    restart can skip a reminder but never sends one twice.
    """
    window = timedelta(days=settings.daily_reminder_window_days)
    day_start = datetime.combine(today, time.min, tzinfo=UTC)
    stmt = (
        select(User)
        .where(
            User.is_banned.is_(False),
            User.blocked_bot_at.is_(None),
            User.reminders_enabled.is_(True),
            or_(User.last_reminded_on.is_(None), User.last_reminded_on < today),
            or_(
                and_(User.last_daily_on >= today - window, User.last_daily_on < today),
                and_(
                    User.last_daily_on.is_(None),
                    User.started_at >= day_start - window,
                    User.started_at < day_start,
                ),
            ),
        )
        .order_by(User.id)
        .limit(limit)
    )
    users = list((await session.execute(stmt)).scalars().all())
    for user in users:
        user.last_reminded_on = today
    await session.flush()
    return users
