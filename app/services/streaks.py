"""Daily-claim streak arithmetic on UTC calendar days.

``User.streak`` is only rewritten on the next claim, so after a missed day it
still holds the old run. Anything shown to the user or checked against a task
must go through :func:`current_streak`.
"""

from datetime import UTC, date, datetime, timedelta

from app.db.models import User


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_today() -> date:
    return utc_now().date()


def _alive(user: User, today: date) -> bool:
    return user.last_daily_on is not None and user.last_daily_on >= today - timedelta(days=1)


def next_streak(user: User, today: date) -> int:
    if user.last_daily_on is None:
        return 1
    if user.last_daily_on == today:
        return user.streak
    if user.last_daily_on == today - timedelta(days=1):
        return user.streak + 1
    return 1


def current_streak(user: User, today: date | None = None) -> int:
    """Streak that is still alive: the last claim was today or yesterday."""
    return user.streak if _alive(user, today or utc_today()) else 0


def broken_streak(user: User, today: date | None = None) -> int:
    """Length of a run that lapsed because a whole day was missed, else 0."""
    if user.last_daily_on is None or _alive(user, today or utc_today()):
        return 0
    return user.streak
