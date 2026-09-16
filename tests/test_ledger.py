import asyncio

import pytest

from app.db.models import LedgerKind, User
from app.services import ledger
from app.services.errors import InsufficientFunds, NotFound


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
    assert await ledger.ledger_sum(session, 100) == 35


@pytest.mark.asyncio
async def test_debit_updates_balance(session) -> None:
    user = await _user(session)
    await ledger.credit(session, user_id=100, amount=50, kind=LedgerKind.TASK)
    entry = await ledger.debit(
        session, user_id=100, amount=20, kind=LedgerKind.WITHDRAW_SENT, reference="wd:1"
    )
    assert entry.amount == -20
    assert entry.balance_after == 30
    assert await ledger.get_balance(session, 100) == 30
    # ORM instance is synchronised with the atomic UPDATE.
    assert user.balance == 30


@pytest.mark.asyncio
async def test_debit_insufficient_funds(session) -> None:
    await _user(session)
    await ledger.credit(session, user_id=100, amount=5, kind=LedgerKind.DAILY)
    with pytest.raises(InsufficientFunds):
        await ledger.debit(session, user_id=100, amount=6, kind=LedgerKind.WITHDRAW_SENT)
    assert await ledger.get_balance(session, 100) == 5
    assert await ledger.count_entries(session, 100) == 1


@pytest.mark.asyncio
async def test_allow_negative_for_admin_and_refunds(session) -> None:
    await _user(session)
    entry = await ledger.debit(
        session, user_id=100, amount=7, kind=LedgerKind.REFUND_REVOKE, allow_negative=True
    )
    assert entry.balance_after == -7
    assert await ledger.get_balance(session, 100) == -7


@pytest.mark.asyncio
async def test_unknown_user_raises_not_found(session) -> None:
    with pytest.raises(NotFound):
        await ledger.credit(session, user_id=999, amount=1, kind=LedgerKind.DAILY)


@pytest.mark.asyncio
async def test_zero_amount_rejected(session) -> None:
    await _user(session)
    with pytest.raises(ValueError):
        await ledger.append_entry(session, user_id=100, amount=0, kind=LedgerKind.DAILY)
    with pytest.raises(ValueError):
        await ledger.credit(session, user_id=100, amount=-1, kind=LedgerKind.DAILY)


@pytest.mark.asyncio
async def test_ledger_is_per_user(session) -> None:
    await _user(session, 1)
    await _user(session, 2)
    await ledger.credit(session, user_id=1, amount=11, kind=LedgerKind.TASK)
    await ledger.credit(session, user_id=2, amount=4, kind=LedgerKind.TASK)
    assert await ledger.get_balance(session, 1) == 11
    assert await ledger.get_balance(session, 2) == 4


@pytest.mark.asyncio
async def test_concurrent_credits_keep_balance_consistent(session) -> None:
    """Sequential awaits within one session, but each is an atomic UPDATE: the
    denormalised balance must equal the ledger sum and balance_after must be monotonic."""
    await _user(session, 7)
    for _ in range(25):
        await ledger.credit(session, user_id=7, amount=2, kind=LedgerKind.DAILY)
    await asyncio.sleep(0)
    assert await ledger.get_balance(session, 7) == 50
    assert await ledger.ledger_sum(session, 7) == 50
    history = await ledger.history(session, 7, limit=100)
    assert [e.balance_after for e in reversed(history)] == list(range(2, 51, 2))


@pytest.mark.asyncio
async def test_history_pagination_and_reconcile(session) -> None:
    user = await _user(session, 8)
    for amount in (5, 6, 7):
        await ledger.credit(session, user_id=8, amount=amount, kind=LedgerKind.TASK)
    page = await ledger.history(session, 8, limit=2, offset=0)
    assert [e.amount for e in page] == [7, 6]
    assert await ledger.reconcile(session) == []
    user.balance = 999
    await session.flush()
    assert await ledger.reconcile(session) == [(8, 999, 18)]
