from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    OPEN_WITHDRAWAL_STATUSES,
    Broadcast,
    DailyClaim,
    LedgerEntry,
    Payment,
    PaymentStatus,
    PromoRedemption,
    User,
    UserTask,
    Withdrawal,
    WithdrawalStatus,
)


@dataclass(slots=True)
class Dashboard:
    users_total: int = 0
    users_today: int = 0
    users_7d: int = 0
    users_30d: int = 0
    dau: int = 0
    wau: int = 0
    banned: int = 0
    blocked_bot: int = 0
    referred: int = 0
    activated: int = 0
    total_balance: int = 0
    held: int = 0
    credited_by_kind: dict[str, int] = field(default_factory=dict)
    credited_total: int = 0
    credited_today: int = 0
    withdraw_pending_count: int = 0
    withdraw_pending_sum: int = 0
    withdraw_approved_count: int = 0
    withdraw_approved_sum: int = 0
    withdraw_sent_count: int = 0
    withdraw_sent_sum: int = 0
    withdraw_rejected_count: int = 0
    payments_count: int = 0
    revenue_xtr: int = 0
    revenue_xtr_30d: int = 0
    refunds_count: int = 0
    daily_claims_today: int = 0
    tasks_completed: int = 0
    promo_redemptions: int = 0
    device_verified: int = 0
    twinks: int = 0
    last_broadcast: Broadcast | None = None

    @property
    def activation_rate(self) -> float:
        return (self.activated / self.referred * 100) if self.referred else 0.0


async def _count(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar_one() or 0)


async def dashboard(session: AsyncSession) -> Dashboard:
    now = datetime.now(UTC)
    today = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
    d1 = now - timedelta(days=1)
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)
    users = select(func.count()).select_from(User)

    data = Dashboard()
    data.users_total = await _count(session, users)
    data.users_today = await _count(session, users.where(User.created_at >= today))
    data.users_7d = await _count(session, users.where(User.created_at >= d7))
    data.users_30d = await _count(session, users.where(User.created_at >= d30))
    data.dau = await _count(session, users.where(User.last_action_at >= d1))
    data.wau = await _count(session, users.where(User.last_action_at >= d7))
    data.banned = await _count(session, users.where(User.is_banned.is_(True)))
    data.blocked_bot = await _count(session, users.where(User.blocked_bot_at.is_not(None)))
    data.referred = await _count(session, users.where(User.referred_by_id.is_not(None)))
    data.activated = await _count(session, users.where(User.referral_activated.is_(True)))
    data.total_balance = await _count(session, select(func.coalesce(func.sum(User.balance), 0)))

    data.held = await _count(
        session,
        select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(
            Withdrawal.status.in_(OPEN_WITHDRAWAL_STATUSES)
        ),
    )

    by_kind = await session.execute(
        select(LedgerEntry.kind, func.coalesce(func.sum(LedgerEntry.amount), 0))
        .where(LedgerEntry.amount > 0)
        .group_by(LedgerEntry.kind)
    )
    data.credited_by_kind = {str(kind): int(total) for kind, total in by_kind.all()}
    data.credited_total = sum(data.credited_by_kind.values())
    data.credited_today = await _count(
        session,
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.amount > 0, LedgerEntry.created_at >= today
        ),
    )

    wd_rows = await session.execute(
        select(Withdrawal.status, func.count(), func.coalesce(func.sum(Withdrawal.amount), 0)).group_by(
            Withdrawal.status
        )
    )
    for status, count, total in wd_rows.all():
        if status == WithdrawalStatus.PENDING.value:
            data.withdraw_pending_count, data.withdraw_pending_sum = int(count), int(total)
        elif status == WithdrawalStatus.APPROVED_MANUAL.value:
            data.withdraw_approved_count, data.withdraw_approved_sum = int(count), int(total)
        elif status == WithdrawalStatus.SENT.value:
            data.withdraw_sent_count, data.withdraw_sent_sum = int(count), int(total)
        elif status == WithdrawalStatus.REJECTED.value:
            data.withdraw_rejected_count = int(count)

    paid = select(Payment).where(Payment.status == PaymentStatus.PAID.value).subquery()
    data.payments_count = await _count(session, select(func.count()).select_from(paid))
    data.revenue_xtr = await _count(session, select(func.coalesce(func.sum(paid.c.xtr_amount), 0)))
    data.revenue_xtr_30d = await _count(
        session,
        select(func.coalesce(func.sum(paid.c.xtr_amount), 0)).where(paid.c.created_at >= d30),
    )
    data.refunds_count = await _count(
        session,
        select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.REFUNDED.value),
    )
    data.daily_claims_today = await _count(
        session,
        select(func.count()).select_from(DailyClaim).where(DailyClaim.claimed_on == now.date()),
    )
    data.tasks_completed = await _count(session, select(func.count()).select_from(UserTask))
    data.promo_redemptions = await _count(session, select(func.count()).select_from(PromoRedemption))
    data.device_verified = await _count(session, users.where(User.device_verified_at.is_not(None)))
    data.twinks = await _count(session, users.where(User.twink_of.is_not(None), User.is_trusted.is_(False)))
    last = await session.execute(select(Broadcast).order_by(Broadcast.id.desc()).limit(1))
    data.last_broadcast = last.scalar_one_or_none()
    return data


async def registrations_by_day(session: AsyncSession, *, days: int = 7) -> list[tuple[str, int]]:
    since = datetime.now(UTC) - timedelta(days=days - 1)
    since = datetime.combine(since.date(), datetime.min.time(), tzinfo=UTC)
    day = func.date(User.created_at)
    result = await session.execute(
        select(day, func.count()).where(User.created_at >= since).group_by(day).order_by(day)
    )
    return [(str(d), int(c)) for d, c in result.all()]
