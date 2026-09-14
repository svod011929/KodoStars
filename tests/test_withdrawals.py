import pytest

from app.db.models import LedgerKind, User, WithdrawalStatus
from app.services import ledger, withdrawals
from app.services.errors import WithdrawalError


async def _user(session, user_id: int = 50) -> User:
    user = User(id=user_id, first_name="W")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_debit_only_after_confirm_sent(session, settings) -> None:
    user = await _user(session)
    await ledger.credit(session, user_id=user.id, amount=80, kind=LedgerKind.TASK)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    assert wd.status == WithdrawalStatus.PENDING.value
    assert await ledger.get_balance(session, user.id) == 80

    await withdrawals.approve_manual(session, withdrawal=wd, admin_id=1)
    assert wd.status == WithdrawalStatus.APPROVED_MANUAL.value
    assert await ledger.get_balance(session, user.id) == 80

    await withdrawals.confirm_sent(session, withdrawal=wd, admin_id=1)
    assert wd.status == WithdrawalStatus.SENT.value
    assert await ledger.get_balance(session, user.id) == 30


@pytest.mark.asyncio
async def test_reject_does_not_touch_ledger(session, settings) -> None:
    user = await _user(session, 51)
    await ledger.credit(session, user_id=user.id, amount=80, kind=LedgerKind.TASK)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    await withdrawals.reject(session, withdrawal=wd, admin_id=1, note="no")
    assert wd.status == WithdrawalStatus.REJECTED.value
    assert await ledger.get_balance(session, user.id) == 80


@pytest.mark.asyncio
async def test_below_minimum_rejected(session, settings) -> None:
    user = await _user(session, 52)
    await ledger.credit(session, user_id=user.id, amount=80, kind=LedgerKind.TASK)
    with pytest.raises(WithdrawalError):
        await withdrawals.apply(session, user=user, amount=1, settings=settings)
