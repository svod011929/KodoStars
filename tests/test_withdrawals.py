import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app.db.models import LedgerKind, User, Withdrawal, WithdrawalStatus
from app.services import events, ledger, withdrawals
from app.services.errors import WithdrawalError


async def _user(session, user_id: int = 50, credit: int = 80) -> User:
    user = User(id=user_id, first_name="W")
    session.add(user)
    await session.flush()
    if credit:
        await ledger.credit(session, user_id=user.id, amount=credit, kind=LedgerKind.TASK)
    return user


@pytest.mark.asyncio
async def test_apply_holds_funds_and_confirm_sent_keeps_them_debited(session, settings) -> None:
    user = await _user(session)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    assert wd.status == WithdrawalStatus.PENDING.value
    # Hold: balance drops immediately, ledger has a WITHDRAW_HOLD row.
    assert await ledger.get_balance(session, user.id) == 30
    assert await withdrawals.held_total(session, user.id) == 50
    kinds = [e.kind for e in await ledger.history(session, user.id, limit=10)]
    assert LedgerKind.WITHDRAW_HOLD.value in kinds
    assert [e.name for e in events.peek(session)] == ["withdrawal_created"]

    await withdrawals.approve_manual(session, withdrawal=wd, admin_id=1)
    assert wd.status == WithdrawalStatus.APPROVED_MANUAL.value
    assert await ledger.get_balance(session, user.id) == 30

    await withdrawals.confirm_sent(session, withdrawal=wd, admin_id=1)
    assert wd.status == WithdrawalStatus.SENT.value
    assert await ledger.get_balance(session, user.id) == 30
    assert await withdrawals.held_total(session, user.id) == 0
    assert await ledger.ledger_sum(session, user.id) == 30


@pytest.mark.asyncio
async def test_reject_refunds_hold(session, settings) -> None:
    user = await _user(session, 51)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    assert await ledger.get_balance(session, user.id) == 30
    await withdrawals.reject(session, withdrawal=wd, admin_id=1, note="нет активности")
    assert wd.status == WithdrawalStatus.REJECTED.value
    assert wd.admin_note == "нет активности"
    assert await ledger.get_balance(session, user.id) == 80
    assert user.last_withdraw_at is None
    # Rejecting twice must not refund twice.
    with pytest.raises(WithdrawalError):
        await withdrawals.reject(session, withdrawal=wd, admin_id=1, note="again")
    assert await ledger.get_balance(session, user.id) == 80


@pytest.mark.asyncio
async def test_user_can_cancel_only_pending(session, settings) -> None:
    user = await _user(session, 52)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    await withdrawals.cancel(session, withdrawal=wd, user=user)
    assert wd.status == WithdrawalStatus.CANCELLED.value
    assert await ledger.get_balance(session, user.id) == 80

    second = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    await withdrawals.approve_manual(session, withdrawal=second, admin_id=1)
    with pytest.raises(WithdrawalError):
        await withdrawals.cancel(session, withdrawal=second, user=user)

    stranger = await _user(session, 53, credit=0)
    third = await _user(session, 54)
    wd3 = await withdrawals.apply(session, user=third, amount=50, settings=settings)
    with pytest.raises(WithdrawalError):
        await withdrawals.cancel(session, withdrawal=wd3, user=stranger)


@pytest.mark.asyncio
async def test_limits_and_guards(session, settings) -> None:
    user = await _user(session, 55)
    with pytest.raises(WithdrawalError):
        await withdrawals.apply(session, user=user, amount=1, settings=settings)
    with pytest.raises(WithdrawalError):
        await withdrawals.apply(session, user=user, amount=500, settings=settings)

    settings.withdraw_max = 60
    with pytest.raises(WithdrawalError):
        await withdrawals.apply(session, user=user, amount=70, settings=settings)
    settings.withdraw_max = 0

    settings.withdraw_enabled = False
    with pytest.raises(WithdrawalError):
        await withdrawals.apply(session, user=user, amount=50, settings=settings)
    settings.withdraw_enabled = True

    settings.withdraw_min_referrals = 1
    with pytest.raises(WithdrawalError, match="активных рефералов"):
        await withdrawals.apply(session, user=user, amount=50, settings=settings)
    settings.withdraw_min_referrals = 0

    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    assert wd.amount == 50
    with pytest.raises(WithdrawalError, match="открытая заявка"):
        await withdrawals.apply(session, user=user, amount=50, settings=settings)
    assert await ledger.get_balance(session, user.id) == 30


@pytest.mark.asyncio
async def test_cooldown_after_sent(session, settings) -> None:
    user = await _user(session, 56, credit=200)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    await withdrawals.approve_manual(session, withdrawal=wd, admin_id=1)
    await withdrawals.confirm_sent(session, withdrawal=wd, admin_id=1)
    with pytest.raises(WithdrawalError, match="Кулдаун"):
        await withdrawals.apply(session, user=user, amount=50, settings=settings)
    settings.withdraw_cooldown_hours = 0
    second = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    assert second.id != wd.id


@pytest.mark.asyncio
async def test_legacy_request_without_hold_is_debited_on_confirm(session, settings) -> None:
    """Requests created before v1.0 have no hold entry: debit happens on confirm_sent."""
    user = await _user(session, 57)
    legacy = Withdrawal(user_id=user.id, amount=50, status=WithdrawalStatus.PENDING.value)
    session.add(legacy)
    await session.flush()
    assert await ledger.get_balance(session, user.id) == 80

    await withdrawals.approve_manual(session, withdrawal=legacy, admin_id=1)
    await withdrawals.confirm_sent(session, withdrawal=legacy, admin_id=1)
    assert await ledger.get_balance(session, user.id) == 30
    kinds = [e.kind for e in await ledger.history(session, user.id, limit=10)]
    assert LedgerKind.WITHDRAW_SENT.value in kinds

    other = Withdrawal(user_id=user.id, amount=10, status=WithdrawalStatus.PENDING.value)
    session.add(other)
    await session.flush()
    await withdrawals.reject(session, withdrawal=other, admin_id=1, note="legacy")
    assert await ledger.get_balance(session, user.id) == 30  # nothing to refund


@pytest.mark.asyncio
async def test_status_transitions_are_atomic(session, settings) -> None:
    """Admin «Отклонить» and user «Отменить» both see a pending request; only the
    first UPDATE wins, so the hold is refunded exactly once."""
    user = await _user(session, 60)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    await withdrawals.cancel(session, withdrawal=wd, user=user)
    assert await ledger.get_balance(session, user.id) == 80

    # A second actor loaded the row while it was still pending: emulate that stale
    # snapshot without dirtying the object (no autoflush back to the database).
    set_committed_value(wd, "status", WithdrawalStatus.PENDING.value)
    with pytest.raises(WithdrawalError, match="уже закрыта"):
        await withdrawals.reject(session, withdrawal=wd, admin_id=1, note="dup")
    assert wd.status == WithdrawalStatus.CANCELLED.value  # refreshed from the database
    assert await ledger.get_balance(session, user.id) == 80  # no second refund

    set_committed_value(wd, "status", WithdrawalStatus.PENDING.value)
    with pytest.raises(WithdrawalError):
        await withdrawals.approve_manual(session, withdrawal=wd, admin_id=1)
    set_committed_value(wd, "status", WithdrawalStatus.APPROVED_MANUAL.value)
    with pytest.raises(WithdrawalError):
        await withdrawals.confirm_sent(session, withdrawal=wd, admin_id=1)
    assert wd.status == WithdrawalStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_queue_and_totals(session, settings) -> None:
    a = await _user(session, 58)
    b = await _user(session, 59)
    wa = await withdrawals.apply(session, user=a, amount=50, settings=settings)
    wb = await withdrawals.apply(session, user=b, amount=60, settings=settings)
    await withdrawals.approve_manual(session, withdrawal=wb, admin_id=1)

    assert [w.id for w in await withdrawals.list_queue(session)] == [wa.id, wb.id]
    assert await withdrawals.count_queue(session) == 2
    assert await withdrawals.count_queue(session, (WithdrawalStatus.PENDING.value,)) == 1
    totals = await withdrawals.totals(session)
    assert totals["pending_count"] == 1
    assert totals["approved_manual_sum"] == 60
    assert await withdrawals.held_total(session) == 110
