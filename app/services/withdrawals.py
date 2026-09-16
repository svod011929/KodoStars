"""Withdrawal queue with hold semantics.

``apply`` debits the amount immediately (``WITHDRAW_HOLD``) so the user's visible
balance is always what they can still spend. ``reject``/``cancel`` refund the hold,
``confirm_sent`` only flips the status — the Stars already left the ledger.

Legacy rows created before v1.0 (no hold entry) are handled transparently: the
debit happens on ``confirm_sent`` and nothing is refunded on ``reject``.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    OPEN_WITHDRAWAL_STATUSES,
    LedgerEntry,
    LedgerKind,
    User,
    Withdrawal,
    WithdrawalStatus,
)
from app.services import events, ledger
from app.services.antifraud import ensure_not_banned, record_event
from app.services.devices import is_device_ok, withdraw_blocked_by_twink
from app.services.errors import InsufficientFunds, WithdrawalError
from app.services.referrals import activated_invite_count


async def list_user_withdrawals(session: AsyncSession, user_id: int, *, limit: int = 10) -> list[Withdrawal]:
    result = await session.execute(
        select(Withdrawal).where(Withdrawal.user_id == user_id).order_by(Withdrawal.id.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def open_withdrawal(session: AsyncSession, user_id: int) -> Withdrawal | None:
    result = await session.execute(
        select(Withdrawal)
        .where(Withdrawal.user_id == user_id, Withdrawal.status.in_(OPEN_WITHDRAWAL_STATUSES))
        .order_by(Withdrawal.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_queue(
    session: AsyncSession,
    statuses: tuple[str, ...] | None = None,
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[Withdrawal]:
    wanted = statuses or OPEN_WITHDRAWAL_STATUSES
    order = Withdrawal.id.asc() if set(wanted) <= set(OPEN_WITHDRAWAL_STATUSES) else Withdrawal.id.desc()
    result = await session.execute(
        select(Withdrawal).where(Withdrawal.status.in_(wanted)).order_by(order).offset(offset).limit(limit)
    )
    return list(result.scalars().all())


async def count_queue(session: AsyncSession, statuses: tuple[str, ...] | None = None) -> int:
    wanted = statuses or OPEN_WITHDRAWAL_STATUSES
    result = await session.execute(
        select(func.count()).select_from(Withdrawal).where(Withdrawal.status.in_(wanted))
    )
    return int(result.scalar_one())


async def held_total(session: AsyncSession, user_id: int | None = None) -> int:
    stmt = select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(
        Withdrawal.status.in_(OPEN_WITHDRAWAL_STATUSES)
    )
    if user_id is not None:
        stmt = stmt.where(Withdrawal.user_id == user_id)
    return int((await session.execute(stmt)).scalar_one())


async def apply(
    session: AsyncSession,
    *,
    user: User,
    amount: int,
    settings: Settings,
) -> Withdrawal:
    ensure_not_banned(user)
    if not settings.withdraw_enabled:
        raise WithdrawalError("Вывод временно приостановлен. Следите за новостями.")
    if settings.device_check_for_withdraw and not is_device_ok(user, settings):
        raise WithdrawalError(
            "Сначала подтвердите устройство — кнопка «🛡 Подтвердить устройство» в главном меню."
        )
    if withdraw_blocked_by_twink(user, settings):
        raise WithdrawalError(
            "Вывод недоступен: с этого устройства уже зарегистрирован другой аккаунт. "
            "Если это ошибка — напишите в поддержку."
        )
    if amount < settings.withdraw_min:
        raise WithdrawalError(f"Минимум для заявки — {settings.withdraw_min} ⭐")
    if settings.withdraw_max and amount > settings.withdraw_max:
        raise WithdrawalError(f"Максимум для одной заявки — {settings.withdraw_max} ⭐")
    if await open_withdrawal(session, user.id) is not None:
        raise WithdrawalError("У вас уже есть открытая заявка на вывод")
    if settings.withdraw_min_referrals > 0:
        invites = await activated_invite_count(session, user.id)
        if invites < settings.withdraw_min_referrals:
            raise WithdrawalError(
                f"Для вывода нужно {settings.withdraw_min_referrals} активных рефералов (сейчас {invites})."
            )

    if user.last_withdraw_at is not None:
        last = user.last_withdraw_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        cooldown = timedelta(hours=settings.withdraw_cooldown_hours)
        remaining = cooldown - (datetime.now(UTC) - last)
        if remaining > timedelta(0):
            hours = max(int(remaining.total_seconds() // 3600), 0)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            raise WithdrawalError(f"Кулдаун на вывод: ещё {hours} ч {minutes} мин")

    if await ledger.get_balance(session, user.id) < amount:
        raise WithdrawalError("Недостаточно Stars на балансе")

    withdrawal = Withdrawal(
        user_id=user.id,
        amount=amount,
        status=WithdrawalStatus.PENDING.value,
    )
    session.add(withdrawal)
    await session.flush()
    try:
        await ledger.debit(
            session,
            user_id=user.id,
            amount=amount,
            kind=LedgerKind.WITHDRAW_HOLD,
            reference=f"wd:{withdrawal.id}",
        )
    except InsufficientFunds as exc:
        await session.delete(withdrawal)
        await session.flush()
        raise WithdrawalError("Недостаточно Stars на балансе") from exc
    user.last_withdraw_at = datetime.now(UTC)
    await record_event(session, user.id, "withdraw_apply", f"amount={amount}")
    await session.flush()
    events.emit(session, "withdrawal_created", withdrawal_id=withdrawal.id, user_id=user.id)
    return withdrawal


async def _has_hold(session: AsyncSession, withdrawal: Withdrawal) -> bool:
    result = await session.execute(
        select(LedgerEntry.id).where(
            LedgerEntry.kind == LedgerKind.WITHDRAW_HOLD.value,
            LedgerEntry.reference == f"wd:{withdrawal.id}",
        )
    )
    return result.scalar_one_or_none() is not None


async def _refund_hold(session: AsyncSession, withdrawal: Withdrawal, *, reason: str) -> None:
    if not await _has_hold(session, withdrawal):
        return
    already = await session.execute(
        select(LedgerEntry.id).where(
            LedgerEntry.kind == LedgerKind.WITHDRAW_REFUND.value,
            LedgerEntry.reference == f"wd:{withdrawal.id}",
        )
    )
    if already.scalar_one_or_none() is not None:
        return
    await ledger.credit(
        session,
        user_id=withdrawal.user_id,
        amount=withdrawal.amount,
        kind=LedgerKind.WITHDRAW_REFUND,
        reference=f"wd:{withdrawal.id}",
        extra={"reason": reason},
    )


async def _transition(
    session: AsyncSession,
    withdrawal: Withdrawal,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
    error: str,
    **fields: Any,
) -> None:
    """Atomic status change: ``UPDATE … WHERE status IN (from)``.

    Two actors (user «Отменить» vs admin «Отклонить», or a double tap) can both pass
    an in-memory status check; only the one whose UPDATE matches a row proceeds, so
    the refund/debit that follows can never run twice.
    """
    stmt = (
        update(Withdrawal)
        .where(Withdrawal.id == withdrawal.id, Withdrawal.status.in_(from_statuses))
        .values(status=to_status, **fields)
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    if result.rowcount != 1:
        await session.refresh(withdrawal)
        raise WithdrawalError(error)
    await session.refresh(withdrawal)


async def cancel(session: AsyncSession, *, withdrawal: Withdrawal, user: User) -> Withdrawal:
    """User-side cancellation: only while the request is still pending."""
    if withdrawal.user_id != user.id:
        raise WithdrawalError("Это не ваша заявка")
    await _transition(
        session,
        withdrawal,
        from_statuses=(WithdrawalStatus.PENDING.value,),
        to_status=WithdrawalStatus.CANCELLED.value,
        error="Заявку уже обрабатывает администратор — отменить нельзя",
        admin_note="Отменена пользователем",
        reviewed_at=datetime.now(UTC),
    )
    await _refund_hold(session, withdrawal, reason="cancelled")
    user.last_withdraw_at = None
    await session.flush()
    events.emit(session, "withdrawal_cancelled", withdrawal_id=withdrawal.id, user_id=user.id)
    return withdrawal


async def reject(
    session: AsyncSession,
    *,
    withdrawal: Withdrawal,
    admin_id: int,
    note: str,
) -> Withdrawal:
    await _transition(
        session,
        withdrawal,
        from_statuses=OPEN_WITHDRAWAL_STATUSES,
        to_status=WithdrawalStatus.REJECTED.value,
        error="Заявка уже закрыта",
        admin_note=note.strip()[:500] or "Отклонено администратором",
        reviewed_by=admin_id,
        reviewed_at=datetime.now(UTC),
    )
    await _refund_hold(session, withdrawal, reason="rejected")
    user = await session.get(User, withdrawal.user_id)
    if user is not None:
        user.last_withdraw_at = None
    await session.flush()
    events.emit(
        session,
        "withdrawal_status",
        withdrawal_id=withdrawal.id,
        user_id=withdrawal.user_id,
        status=withdrawal.status,
        amount=withdrawal.amount,
        note=withdrawal.admin_note,
    )
    return withdrawal


async def approve_manual(
    session: AsyncSession,
    *,
    withdrawal: Withdrawal,
    admin_id: int,
) -> Withdrawal:
    """Bot API cannot transfer arbitrary XTR to a user. Approve for manual payout."""
    await _transition(
        session,
        withdrawal,
        from_statuses=(WithdrawalStatus.PENDING.value,),
        to_status=WithdrawalStatus.APPROVED_MANUAL.value,
        error="Заявку нельзя согласовать",
        reviewed_by=admin_id,
        reviewed_at=datetime.now(UTC),
        admin_note=None,
    )
    events.emit(
        session,
        "withdrawal_status",
        withdrawal_id=withdrawal.id,
        user_id=withdrawal.user_id,
        status=withdrawal.status,
        amount=withdrawal.amount,
        note="",
    )
    return withdrawal


async def confirm_sent(
    session: AsyncSession,
    *,
    withdrawal: Withdrawal,
    admin_id: int,
) -> Withdrawal:
    await _transition(
        session,
        withdrawal,
        from_statuses=(WithdrawalStatus.APPROVED_MANUAL.value,),
        to_status=WithdrawalStatus.SENT.value,
        error="Сначала согласуйте заявку",
        sent_at=datetime.now(UTC),
        reviewed_by=admin_id,
    )
    if not await _has_hold(session, withdrawal):
        # Legacy request created before hold semantics: debit now.
        await ledger.debit(
            session,
            user_id=withdrawal.user_id,
            amount=withdrawal.amount,
            kind=LedgerKind.WITHDRAW_SENT,
            reference=f"wd:{withdrawal.id}",
            extra={"admin_id": admin_id, "legacy": True},
            allow_negative=True,
        )
    events.emit(
        session,
        "withdrawal_status",
        withdrawal_id=withdrawal.id,
        user_id=withdrawal.user_id,
        status=withdrawal.status,
        amount=withdrawal.amount,
        note="",
    )
    return withdrawal


async def totals(session: AsyncSession) -> dict[str, int]:
    """Aggregate counters for the admin dashboard."""
    rows = await session.execute(
        select(Withdrawal.status, func.count(), func.coalesce(func.sum(Withdrawal.amount), 0)).group_by(
            Withdrawal.status
        )
    )
    out = {f"{status}_count": 0 for status in WithdrawalStatus}
    out.update({f"{status}_sum": 0 for status in WithdrawalStatus})
    for status, count, total in rows.all():
        out[f"{status}_count"] = int(count)
        out[f"{status}_sum"] = int(total)
    return out
