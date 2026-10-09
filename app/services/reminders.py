"""Daily-claim reminders: who is due today, at most one reminder per user per UTC day."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User

BATCH_SIZE = 100
# Reminders keep going out for a few hours after the configured one, so a restart
# shortly after it still delivers them, but nobody gets one in the middle of the night.
# The window never runs past midnight: a reminder is about today's claim.
SEND_WINDOW_HOURS = 3


@dataclass(frozen=True, slots=True)
class Batch:
    users: list[User]
    # Last user id looked at: the ``after_id`` of the next batch, ``None`` once nobody is left.
    cursor: int | None


def in_send_window(now: datetime, settings: Settings) -> bool:
    if not settings.daily_reminder_enabled:
        return False
    return 0 <= now.hour - settings.daily_reminder_hour_utc < SEND_WINDOW_HOURS


async def claim_due(
    session: AsyncSession, *, today: date, settings: Settings, after_id: int = 0, limit: int = BATCH_SIZE
) -> Batch:
    """Next users to remind today (ids above ``after_id``), already marked as reminded.

    Users qualify when they have not claimed today and either claimed within the
    last ``daily_reminder_window_days`` days or started the bot within that window
    without ever claiming. They are marked by a conditional UPDATE before anything is
    sent, so a crash or restart can skip a reminder but never sends one twice, even
    while two bot processes overlap during a deploy.
    """
    window = timedelta(days=settings.daily_reminder_window_days)
    day_start = datetime.combine(today, time.min, tzinfo=UTC)
    not_reminded = or_(User.last_reminded_on.is_(None), User.last_reminded_on < today)
    candidates = await session.scalars(
        select(User.id)
        .where(
            User.id > after_id,
            User.is_banned.is_(False),
            User.blocked_bot_at.is_(None),
            User.reminders_enabled.is_(True),
            not_reminded,
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
    ids = list(candidates.all())
    if not ids:
        return Batch(users=[], cursor=None)
    claimed = await session.scalars(
        update(User)
        .where(User.id.in_(ids), not_reminded)
        .values(last_reminded_on=today)
        .returning(User)
        .execution_options(synchronize_session="fetch")
    )
    return Batch(users=sorted(claimed.all(), key=lambda user: user.id), cursor=ids[-1])
