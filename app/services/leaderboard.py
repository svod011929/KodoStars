from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import LedgerEntry, LedgerKind, ReferralEdge, User

EARNING_KINDS: tuple[str, ...] = (
    LedgerKind.DAILY.value,
    LedgerKind.TASK.value,
    LedgerKind.REFERRAL_BONUS.value,
    LedgerKind.REFERRAL_SHARE.value,
    LedgerKind.PROMO.value,
    LedgerKind.CONTEST_PRIZE.value,
)


@dataclass(frozen=True, slots=True)
class LeaderRow:
    user_id: int
    name: str
    value: int


def mask_name(user: User) -> str:
    """Privacy-friendly display: ``@da***el`` / ``Da***``."""
    source = user.username or user.first_name or str(user.id)
    prefix = "@" if user.username else ""
    if len(source) <= 3:
        return f"{prefix}{source[0]}***"
    return f"{prefix}{source[:2]}***{source[-1]}"


def _activated_referrals() -> Select:
    """Activated L1 referees per referrer — the same rule that pays the referral bonus."""
    referee = aliased(User)
    return (
        select(ReferralEdge.referrer_id.label("user_id"), func.count().label("total"))
        .join(referee, referee.id == ReferralEdge.referee_id)
        .where(ReferralEdge.level == 1, referee.referral_activated.is_(True))
        .group_by(ReferralEdge.referrer_id)
    )


async def _top(session: AsyncSession, totals: Select, limit: int) -> list[LeaderRow]:
    # Banned users are filtered before LIMIT so they never take a slot in the top.
    sub = totals.subquery()
    stmt = (
        select(User, sub.c.total)
        .join(sub, sub.c.user_id == User.id)
        .where(User.is_banned.is_(False))
        .order_by(sub.c.total.desc(), User.id.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [LeaderRow(user_id=user.id, name=mask_name(user), value=int(total)) for user, total in rows]


async def top_referrers(session: AsyncSession, *, limit: int = 10) -> list[LeaderRow]:
    return await _top(session, _activated_referrals(), limit)


async def top_earners(session: AsyncSession, *, limit: int = 10, days: int | None = 7) -> list[LeaderRow]:
    totals = (
        select(LedgerEntry.user_id.label("user_id"), func.sum(LedgerEntry.amount).label("total"))
        .where(LedgerEntry.amount > 0, LedgerEntry.kind.in_(EARNING_KINDS))
        .group_by(LedgerEntry.user_id)
    )
    if days is not None:
        totals = totals.where(LedgerEntry.created_at >= datetime.now(UTC) - timedelta(days=days))
    return await _top(session, totals, limit)


async def user_rank_by_referrals(session: AsyncSession, user_id: int) -> int | None:
    sub = _activated_referrals().subquery()
    mine = await session.scalar(select(sub.c.total).where(sub.c.user_id == user_id))
    if not mine:
        return None
    ahead = await session.scalar(
        select(func.count())
        .select_from(sub)
        .join(User, User.id == sub.c.user_id)
        .where(User.is_banned.is_(False), sub.c.total > mine)
    )
    return int(ahead or 0) + 1
