from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerKind, ReferralEdge, User
from app.services import ledger
from app.services.antifraud import record_event
from app.services.levels import add_xp, apply_multipliers, info_for_xp


def parse_ref_payload(payload: str | None) -> int | None:
    if not payload:
        return None
    raw = payload.strip()
    if raw.startswith("ref_"):
        raw = raw[4:]
    if raw.isdigit():
        return int(raw)
    return None


async def attach_referrer(
    session: AsyncSession,
    *,
    user: User,
    payload: str | None,
    settings: Settings,
) -> list[ReferralEdge]:
    referrer_id = parse_ref_payload(payload)
    if referrer_id is None or user.referred_by_id is not None:
        return []
    if referrer_id == user.id:
        await record_event(session, user.id, "self_referral", "Попытка самореферала")
        return []

    referrer = await session.get(User, referrer_id)
    if referrer is None or referrer.is_banned:
        await record_event(
            session,
            user.id,
            "invalid_referrer",
            f"referrer={referrer_id}",
        )
        return []

    user.referred_by_id = referrer_id
    edges: list[ReferralEdge] = []
    current_id = referrer_id
    for level in range(1, settings.referral_levels + 1):
        if current_id is None:
            break
        ancestor = await session.get(User, current_id)
        if ancestor is None:
            break
        edge = ReferralEdge(referrer_id=current_id, referee_id=user.id, level=level)
        session.add(edge)
        edges.append(edge)
        current_id = ancestor.referred_by_id
    await session.flush()
    return edges


async def activate_if_ready(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    boost_bp: int = 100,
) -> list[ReferralEdge]:
    if user.referral_activated or user.referred_by_id is None:
        return []
    if user.activity_score < settings.min_referral_activity:
        return []

    user.referral_activated = True
    result = await session.execute(
        select(ReferralEdge).where(
            ReferralEdge.referee_id == user.id,
            ReferralEdge.credited_at.is_(None),
        )
    )
    edges = list(result.scalars().all())
    now = datetime.now(UTC)
    for edge in edges:
        referrer = await session.get(User, edge.referrer_id)
        if referrer is None or referrer.is_banned:
            continue
        bonus = settings.referral_bonus(edge.level)
        if bonus <= 0:
            edge.credited_at = now
            continue
        level_bp = info_for_xp(referrer.xp).multiplier_bp
        payout = apply_multipliers(bonus, level_bp, boost_bp)
        if payout <= 0:
            edge.credited_at = now
            continue
        await ledger.credit(
            session,
            user_id=referrer.id,
            amount=payout,
            kind=LedgerKind.REFERRAL_BONUS,
            reference=f"refbonus:{edge.level}:{user.id}",
            extra={"referee_id": user.id, "level": edge.level, "base": bonus},
        )
        await add_xp(session, referrer, 8 if edge.level == 1 else 3)
        edge.credited_at = now
    await session.flush()
    return edges


async def share_earning(
    session: AsyncSession,
    *,
    earner: User,
    base_amount: int,
    settings: Settings,
    source: str,
    boost_bp: int = 100,
) -> None:
    if base_amount <= 0 or not earner.referral_activated:
        return
    result = await session.execute(
        select(ReferralEdge).where(ReferralEdge.referee_id == earner.id)
    )
    for edge in result.scalars().all():
        percent = settings.referral_percent(edge.level)
        if percent <= 0:
            continue
        referrer = await session.get(User, edge.referrer_id)
        if referrer is None or referrer.is_banned:
            continue
        share = (base_amount * percent) // 100
        if share <= 0:
            continue
        level_bp = info_for_xp(referrer.xp).multiplier_bp
        payout = apply_multipliers(share, level_bp, boost_bp)
        if payout <= 0:
            continue
        await ledger.credit(
            session,
            user_id=referrer.id,
            amount=payout,
            kind=LedgerKind.REFERRAL_SHARE,
            reference=f"refshare:{edge.level}:{earner.id}:{source}",
            extra={
                "referee_id": earner.id,
                "level": edge.level,
                "source": source,
                "base": base_amount,
            },
        )


async def referral_stats(session: AsyncSession, user_id: int) -> dict[int, int]:
    result = await session.execute(
        select(ReferralEdge.level, func.count())
        .where(ReferralEdge.referrer_id == user_id)
        .group_by(ReferralEdge.level)
    )
    stats = {1: 0, 2: 0}
    for level, count in result.all():
        stats[int(level)] = int(count)
    return stats


async def activated_invite_count(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ReferralEdge)
        .join(User, User.id == ReferralEdge.referee_id)
        .where(
            ReferralEdge.referrer_id == user_id,
            ReferralEdge.level == 1,
            User.referral_activated.is_(True),
        )
    )
    return int(result.scalar_one())
