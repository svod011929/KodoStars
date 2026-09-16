from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry, LedgerKind, ReferralEdge, User

EARNING_KINDS: tuple[str, ...] = (
    LedgerKind.DAILY.value,
    LedgerKind.TASK.value,
    LedgerKind.REFERRAL_BONUS.value,
    LedgerKind.REFERRAL_SHARE.value,
    LedgerKind.PROMO.value,
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


async def top_referrers(session: AsyncSession, *, limit: int = 10) -> list[LeaderRow]:
    stmt = (
        select(ReferralEdge.referrer_id, func.count().label("total"))
        .where(ReferralEdge.level == 1)
        .group_by(ReferralEdge.referrer_id)
        .order_by(func.count().desc(), ReferralEdge.referrer_id.asc())
        .limit(limit)
    )
    return await _hydrate(session, (await session.execute(stmt)).all())


async def top_earners(session: AsyncSession, *, limit: int = 10, days: int | None = 7) -> list[LeaderRow]:
    stmt = (
        select(LedgerEntry.user_id, func.coalesce(func.sum(LedgerEntry.amount), 0).label("total"))
        .where(LedgerEntry.amount > 0, LedgerEntry.kind.in_(EARNING_KINDS))
        .group_by(LedgerEntry.user_id)
        .order_by(func.sum(LedgerEntry.amount).desc(), LedgerEntry.user_id.asc())
        .limit(limit)
    )
    if days is not None:
        stmt = stmt.where(LedgerEntry.created_at >= datetime.now(UTC) - timedelta(days=days))
    return await _hydrate(session, (await session.execute(stmt)).all())


async def user_rank_by_referrals(session: AsyncSession, user_id: int) -> int | None:
    mine = await session.execute(
        select(func.count()).where(ReferralEdge.referrer_id == user_id, ReferralEdge.level == 1)
    )
    my_total = int(mine.scalar_one())
    if my_total == 0:
        return None
    better = (
        select(ReferralEdge.referrer_id)
        .where(ReferralEdge.level == 1)
        .group_by(ReferralEdge.referrer_id)
        .having(func.count() > my_total)
        .subquery()
    )
    ahead = await session.execute(select(func.count()).select_from(better))
    return int(ahead.scalar_one()) + 1


async def _hydrate(session: AsyncSession, rows) -> list[LeaderRow]:
    out: list[LeaderRow] = []
    for user_id, total in rows:
        user = await session.get(User, int(user_id))
        if user is None or user.is_banned:
            continue
        out.append(LeaderRow(user_id=user.id, name=mask_name(user), value=int(total)))
    return out
