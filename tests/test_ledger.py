import pytest

from app.db.models import LedgerKind, User
from app.services import ledger
from app.services.errors import InsufficientFunds


async def _user(session, user_id: int = 100) -> User:
    user = User(id=user_id, first_name="Test")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_credit_and_balance(session) -> None:
    await _user(session)
    await ledger.credit(session, user_id=100, amount=25, kind=LedgerKind.SIGNUP)
    await ledger.credit(session, user_id=100, amount=10, kind=LedgerKind.DAILY)
    assert await ledger.get_balance(session, 100) == 35


@pytest.mark.asyncio
async def test_debit_updates_balance(session) -> None:
    await _user(session)
    await ledger.credit(session, user_id=100, amount=50, kind=LedgerKind.TASK)
    entry = await ledger.debit(
        session, user_id=100, amount=20, kind=LedgerKind.WITHDRAW_SENT, reference="wd:1"
    )
    assert entry.amount == -20
    assert entry.balance_after == 30
    assert await ledger.get_balance(session, 100) == 30


@pytest.mark.asyncio
async def test_debit_insufficient_funds(session) -> None:
    await _user(session)
    await ledger.credit(session, user_id=100, amount=5, kind=LedgerKind.DAILY)
    with pytest.raises(InsufficientFunds):
        await ledger.debit(session, user_id=100, amount=6, kind=LedgerKind.WITHDRAW_SENT)


@pytest.mark.asyncio
async def test_ledger_is_per_user(session) -> None:
    await _user(session, 1)
    await _user(session, 2)
    await ledger.credit(session, user_id=1, amount=11, kind=LedgerKind.TASK)
    await ledger.credit(session, user_id=2, amount=4, kind=LedgerKind.TASK)
    assert await ledger.get_balance(session, 1) == 11
    assert await ledger.get_balance(session, 2) == 4
