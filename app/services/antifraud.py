from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import FraudEvent, ReferralEdge, User
from app.services.errors import CooldownActive, UserBanned


async def record_event(
    session: AsyncSession,
    user_id: int,
    kind: str,
    detail: str = "",
) -> FraudEvent:
    event = FraudEvent(user_id=user_id, kind=kind, detail=detail[:2000])
    session.add(event)
    await session.flush()
    return event


def ensure_not_banned(user: User) -> None:
    if user.is_banned:
        raise UserBanned(user.ban_reason or "Аккаунт заблокирован")


def ensure_action_cooldown(user: User, settings: Settings) -> None:
    if not user.last_action_at or settings.claim_cooldown_seconds <= 0:
        return
    last = user.last_action_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    elapsed = datetime.now(UTC) - last
    wait = timedelta(seconds=settings.claim_cooldown_seconds)
    if elapsed < wait:
        raise CooldownActive("Слишком часто. Подождите пару секунд.")


async def bump_activity(session: AsyncSession, user: User, points: int = 1) -> None:
    user.activity_score += max(points, 0)
    user.last_action_at = datetime.now(UTC)
    await session.flush()


async def set_ban(
    session: AsyncSession,
    user: User,
    *,
    banned: bool,
    reason: str,
    admin_id: int,
) -> None:
    user.is_banned = banned
    user.ban_reason = reason if banned else None
    await record_event(
        session,
        user.id,
        "ban" if banned else "unban",
        f"admin={admin_id}; {reason}",
    )
    await session.flush()


async def recent_events(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[FraudEvent]:
    stmt = select(FraudEvent).order_by(FraudEvent.id.desc()).offset(offset).limit(limit)
    if user_id is not None:
        stmt = stmt.where(FraudEvent.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_events(session: AsyncSession, *, user_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(FraudEvent)
    if user_id is not None:
        stmt = stmt.where(FraudEvent.user_id == user_id)
    return int((await session.execute(stmt)).scalar_one())


async def suspicious_referrers(
    session: AsyncSession,
    *,
    min_referrals: int = 5,
    limit: int = 15,
) -> list[tuple[User, int, int]]:
    """Users with many L1 referrals but a low activation ratio.

    Returns ``(user, total_l1, activated_l1)`` sorted by the worst ratio first.
    """
    activated = func.sum(case((User.referral_activated.is_(True), 1), else_=0))
    stmt = (
        select(ReferralEdge.referrer_id, func.count().label("total"), activated.label("act"))
        .join(User, User.id == ReferralEdge.referee_id)
        .where(ReferralEdge.level == 1)
        .group_by(ReferralEdge.referrer_id)
        .having(func.count() >= min_referrals)
        .order_by((activated * 100 / func.count()).asc(), func.count().desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    out: list[tuple[User, int, int]] = []
    for referrer_id, total, act in rows:
        user = await session.get(User, int(referrer_id))
        if user is not None:
            out.append((user, int(total), int(act or 0)))
    return out
