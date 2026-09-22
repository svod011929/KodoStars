from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerEntry, LedgerKind, ReferralEdge, User
from app.services import ambassadors as amb_service
from app.services import events, ledger
from app.services.antifraud import record_event
from app.services.devices import is_device_ok, referral_blocked_by_twink
from app.services.levels import XP_REFERRAL_L1, XP_REFERRAL_L2, add_xp, apply_multipliers, info_for_xp
from app.services.piarflow_quality import paid_sub_count


def parse_ref_payload(payload: str | None) -> int | None:
    if not payload:
        return None
    raw = payload.strip()
    if raw.startswith("ref_"):
        raw = raw[4:]
    if raw.isdigit():
        return int(raw)
    return None


def referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


async def attach_referrer(
    session: AsyncSession,
    *,
    user: User,
    payload: str | None,
    settings: Settings,
    first_start: bool = True,
) -> list[ReferralEdge]:
    """Bind ``user`` to a referrer chain.

    Only allowed on the very first ``/start`` (``first_start``) so existing accounts
    cannot be re-attributed by clicking someone else's link later.
    """
    referrer_id = parse_ref_payload(payload)
    if referrer_id is None or user.referred_by_id is not None:
        return []
    if await _already_attached(session, user):
        return []
    if not first_start:
        await record_event(session, user.id, "late_referral", f"referrer={referrer_id}")
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

    # Resolve the whole chain first, then insert: no autoflush half-way through.
    chain: list[int] = []
    current_id: int | None = referrer_id
    for _level in range(settings.referral_levels):
        if current_id is None:
            break
        ancestor = await session.get(User, current_id)
        if ancestor is None or ancestor.id == user.id or current_id in chain:
            break
        chain.append(current_id)
        current_id = ancestor.referred_by_id

    user.referred_by_id = referrer_id
    edges = [
        ReferralEdge(referrer_id=ancestor_id, referee_id=user.id, level=level)
        for level, ancestor_id in enumerate(chain, start=1)
    ]
    session.add_all(edges)
    await session.flush()
    if settings.notify_referrer:
        events.emit(
            session,
            "referral_joined",
            referrer_id=referrer_id,
            referee_id=user.id,
            referee_name=user.display_name,
        )
    return edges


async def _already_attached(session: AsyncSession, user: User) -> bool:
    """Idempotency guard: edges may already exist for this referee.

    This is the state left behind when two ``/start`` updates raced before
    per-user serialisation existed. Repair ``referred_by_id`` from the L1 edge so
    the account is consistent and never re-attributed.
    """
    result = await session.execute(
        select(ReferralEdge).where(ReferralEdge.referee_id == user.id).order_by(ReferralEdge.level)
    )
    existing = list(result.scalars().all())
    if not existing:
        return False
    if user.referred_by_id is None:
        user.referred_by_id = existing[0].referrer_id
        await session.flush()
        await record_event(session, user.id, "referral_repaired", f"referrer={existing[0].referrer_id}")
    return True


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
    # Anti-multiaccount: wait for the device check; never pay for a flagged twink.
    # Both conditions are reversible (verification later / admin trust), so nothing is
    # marked as credited here — the next activity simply re-evaluates.
    if not is_device_ok(user, settings) or referral_blocked_by_twink(user, settings):
        return []
    # Traffic quality: PiarFlow must have credited ≥N paid subscriptions for this user.
    needed = max(int(settings.referral_min_piarflow_subs), 0)
    if needed and await paid_sub_count(session, user.id) < needed:
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
    terms_cache: dict[int, amb_service.ReferralTerms] = {}
    for edge in edges:
        referrer = await session.get(User, edge.referrer_id)
        if referrer is None or referrer.is_banned:
            edge.credited_at = now
            continue
        if referrer.id not in terms_cache:
            terms_cache[referrer.id] = await amb_service.effective_referral_terms(
                session, referrer.id, settings
            )
        bonus = terms_cache[referrer.id].bonus(edge.level)
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
        await add_xp(session, referrer, XP_REFERRAL_L1 if edge.level == 1 else XP_REFERRAL_L2)
        edge.credited_at = now
        if settings.notify_referrer:
            events.emit(
                session,
                "referral_activated",
                referrer_id=referrer.id,
                referee_id=user.id,
                referee_name=user.display_name,
                level=edge.level,
                amount=payout,
            )
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
    result = await session.execute(select(ReferralEdge).where(ReferralEdge.referee_id == earner.id))
    terms_cache: dict[int, amb_service.ReferralTerms] = {}
    for edge in result.scalars().all():
        referrer = await session.get(User, edge.referrer_id)
        if referrer is None or referrer.is_banned:
            continue
        if referrer.id not in terms_cache:
            terms_cache[referrer.id] = await amb_service.effective_referral_terms(
                session, referrer.id, settings
            )
        percent = terms_cache[referrer.id].percent(edge.level)
        if percent <= 0:
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
            reference=f"refshare:{edge.level}:{earner.id}:{source}"[:64],
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


async def referral_earnings(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.user_id == user_id,
            LedgerEntry.kind.in_((LedgerKind.REFERRAL_BONUS.value, LedgerKind.REFERRAL_SHARE.value)),
        )
    )
    return int(result.scalar_one())


async def list_referrals(
    session: AsyncSession,
    user_id: int,
    *,
    level: int = 1,
    limit: int = 10,
    offset: int = 0,
) -> list[User]:
    result = await session.execute(
        select(User)
        .join(ReferralEdge, ReferralEdge.referee_id == User.id)
        .where(ReferralEdge.referrer_id == user_id, ReferralEdge.level == level)
        .order_by(ReferralEdge.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())
