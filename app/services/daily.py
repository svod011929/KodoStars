from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import DailyClaim, LedgerKind, User
from app.services import ledger, referrals
from app.services.antifraud import bump_activity, ensure_action_cooldown, ensure_not_banned
from app.services.boosts import active_multiplier_bp
from app.services.errors import AlreadyClaimed
from app.services.levels import XP_DAILY, add_xp, apply_multipliers, info_for_xp
from app.services.tasks import try_complete_event


@dataclass(frozen=True, slots=True)
class DailyPreview:
    claimed_today: bool
    streak_if_claimed: int
    base_reward: int
    estimated_reward: int
    seconds_until_reset: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_today() -> date:
    return utc_now().date()


def next_streak(user: User, today: date) -> int:
    if user.last_daily_on is None:
        return 1
    if user.last_daily_on == today:
        return user.streak
    if user.last_daily_on == today - timedelta(days=1):
        return user.streak + 1
    return 1


def base_reward_for(streak: int, settings: Settings) -> int:
    streak_bonus = min(max(streak - 1, 0), settings.daily_streak_cap) * settings.daily_streak_bonus
    return settings.daily_base_reward + streak_bonus


def seconds_until_utc_midnight(now: datetime | None = None) -> int:
    now = now or utc_now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return max(int((tomorrow - now).total_seconds()), 0)


async def preview(session: AsyncSession, *, user: User, settings: Settings) -> DailyPreview:
    today = utc_today()
    claimed = user.last_daily_on == today
    streak = next_streak(user, today) if not claimed else user.streak + 1
    base = base_reward_for(streak, settings)
    level_bp = info_for_xp(user.xp).multiplier_bp
    boost_bp = await active_multiplier_bp(session, user.id)
    return DailyPreview(
        claimed_today=claimed,
        streak_if_claimed=streak,
        base_reward=base,
        estimated_reward=apply_multipliers(base, level_bp, boost_bp),
        seconds_until_reset=seconds_until_utc_midnight(),
    )


async def claim_daily(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
) -> DailyClaim:
    ensure_not_banned(user)
    ensure_action_cooldown(user, settings)
    today = utc_today()
    existing = await session.execute(
        select(DailyClaim).where(DailyClaim.user_id == user.id, DailyClaim.claimed_on == today)
    )
    if existing.scalar_one_or_none() is not None:
        raise AlreadyClaimed("Ежедневная награда уже получена сегодня")

    streak = next_streak(user, today)
    base = base_reward_for(streak, settings)
    level_bp = info_for_xp(user.xp).multiplier_bp
    boost_bp = await active_multiplier_bp(session, user.id)
    amount = apply_multipliers(base, level_bp, boost_bp)

    claim = DailyClaim(user_id=user.id, claimed_on=today, streak=streak, amount=amount)
    session.add(claim)
    user.streak = streak
    user.last_daily_on = today
    await ledger.credit(
        session,
        user_id=user.id,
        amount=amount,
        kind=LedgerKind.DAILY,
        reference=f"daily:{today.isoformat()}",
        extra={"streak": streak, "base": base},
    )
    await add_xp(session, user, XP_DAILY)
    await bump_activity(session, user, 1)
    await referrals.activate_if_ready(session, user=user, settings=settings, boost_bp=boost_bp)
    await referrals.share_earning(
        session,
        earner=user,
        base_amount=amount,
        settings=settings,
        source="daily",
        boost_bp=boost_bp,
    )
    await try_complete_event(session, user=user, event="daily_claimed", settings=settings)
    if user.referred_by_id:
        referrer = await session.get(User, user.referred_by_id)
        if referrer is not None and not referrer.is_banned:
            await try_complete_event(session, user=referrer, event="invite_activated", settings=settings)
    await session.flush()
    return claim
