from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerKind, User, Withdrawal, WithdrawalStatus
from app.services import ledger
from app.services.antifraud import ensure_not_banned, record_event
from app.services.errors import WithdrawalError


async def list_user_withdrawals(session: AsyncSession, user_id: int) -> list[Withdrawal]:
    result = await session.execute(
        select(Withdrawal)
        .where(Withdrawal.user_id == user_id)
        .order_by(Withdrawal.id.desc())
        .limit(10)
    )
    return list(result.scalars().all())


async def list_queue(
    session: AsyncSession, statuses: tuple[str, ...] | None = None
) -> list[Withdrawal]:
    wanted = statuses or (WithdrawalStatus.PENDING.value, WithdrawalStatus.APPROVED_MANUAL.value)
    result = await session.execute(
        select(Withdrawal)
        .where(Withdrawal.status.in_(wanted))
        .order_by(Withdrawal.id.asc())
        .limit(30)
    )
    return list(result.scalars().all())


async def apply(
    session: AsyncSession,
    *,
    user: User,
    amount: int,
    settings: Settings,
) -> Withdrawal:
    ensure_not_banned(user)
    if amount < settings.withdraw_min:
        raise WithdrawalError(f"Минимум для заявки — {settings.withdraw_min} ⭐")

    pending = await session.execute(
        select(Withdrawal).where(
            Withdrawal.user_id == user.id,
            Withdrawal.status.in_(
                (WithdrawalStatus.PENDING.value, WithdrawalStatus.APPROVED_MANUAL.value)
            ),
        )
    )
    if pending.scalars().first() is not None:
        raise WithdrawalError("У вас уже есть открытая заявка на вывод")

    if user.last_withdraw_at is not None:
        last = user.last_withdraw_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        cooldown = timedelta(hours=settings.withdraw_cooldown_hours)
        if datetime.now(UTC) - last < cooldown:
            raise WithdrawalError("Ещё действует кулдаун на вывод")

    balance = await ledger.get_balance(session, user.id)
    if balance < amount:
        raise WithdrawalError("Недостаточно Stars на балансе")

    withdrawal = Withdrawal(
        user_id=user.id,
        amount=amount,
        status=WithdrawalStatus.PENDING.value,
    )
    session.add(withdrawal)
    user.last_withdraw_at = datetime.now(UTC)
    await record_event(session, user.id, "withdraw_apply", f"amount={amount}")
    await session.flush()
    return withdrawal


async def reject(
    session: AsyncSession,
    *,
    withdrawal: Withdrawal,
    admin_id: int,
    note: str,
) -> Withdrawal:
    if withdrawal.status not in {
        WithdrawalStatus.PENDING.value,
        WithdrawalStatus.APPROVED_MANUAL.value,
    }:
        raise WithdrawalError("Заявка уже закрыта")
    withdrawal.status = WithdrawalStatus.REJECTED.value
    withdrawal.admin_note = note
    withdrawal.reviewed_by = admin_id
    withdrawal.reviewed_at = datetime.now(UTC)
    await session.flush()
    return withdrawal


async def approve_manual(
    session: AsyncSession,
    *,
    withdrawal: Withdrawal,
    admin_id: int,
) -> Withdrawal:
    """Bot API cannot transfer arbitrary XTR to a user. Approve for manual payout."""
    if withdrawal.status != WithdrawalStatus.PENDING.value:
        raise WithdrawalError("Заявку нельзя согласовать")
    withdrawal.status = WithdrawalStatus.APPROVED_MANUAL.value
    withdrawal.reviewed_by = admin_id
    withdrawal.reviewed_at = datetime.now(UTC)
    withdrawal.admin_note = (
        "Bot API не умеет автоматически отправлять Stars пользователю. "
        "Отправьте Stars вручную (подарок Stars с личного аккаунта / согласованный канал), "
        "затем нажмите «Подтвердить отправку». Списание с леджера — только после подтверждения."
    )
    await session.flush()
    return withdrawal


async def confirm_sent(
    session: AsyncSession,
    *,
    withdrawal: Withdrawal,
    admin_id: int,
) -> Withdrawal:
    if withdrawal.status != WithdrawalStatus.APPROVED_MANUAL.value:
        raise WithdrawalError("Сначала согласуйте заявку")
    await ledger.debit(
        session,
        user_id=withdrawal.user_id,
        amount=withdrawal.amount,
        kind=LedgerKind.WITHDRAW_SENT,
        reference=f"wd:{withdrawal.id}",
        extra={"admin_id": admin_id},
    )
    withdrawal.status = WithdrawalStatus.SENT.value
    withdrawal.sent_at = datetime.now(UTC)
    withdrawal.reviewed_by = admin_id
    await session.flush()
    return withdrawal
