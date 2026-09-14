from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry, LedgerKind
from app.services.errors import InsufficientFunds


async def get_balance(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.user_id == user_id
        )
    )
    return int(result.scalar_one())


async def append_entry(
    session: AsyncSession,
    *,
    user_id: int,
    amount: int,
    kind: LedgerKind | str,
    reference: str | None = None,
    extra: Mapping[str, Any] | None = None,
    allow_negative: bool = False,
) -> LedgerEntry:
    if amount == 0:
        raise ValueError("ledger amount must be non-zero")

    current = await get_balance(session, user_id)
    next_balance = current + amount
    if next_balance < 0 and not allow_negative:
        raise InsufficientFunds("Недостаточно Stars на балансе")

    entry = LedgerEntry(
        user_id=user_id,
        amount=amount,
        balance_after=next_balance,
        kind=kind.value if isinstance(kind, LedgerKind) else kind,
        reference=reference,
        extra=dict(extra) if extra else None,
    )
    session.add(entry)
    await session.flush()
    return entry


async def credit(
    session: AsyncSession,
    *,
    user_id: int,
    amount: int,
    kind: LedgerKind | str,
    reference: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> LedgerEntry:
    if amount <= 0:
        raise ValueError("credit amount must be positive")
    return await append_entry(
        session,
        user_id=user_id,
        amount=amount,
        kind=kind,
        reference=reference,
        extra=extra,
    )


async def debit(
    session: AsyncSession,
    *,
    user_id: int,
    amount: int,
    kind: LedgerKind | str,
    reference: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> LedgerEntry:
    if amount <= 0:
        raise ValueError("debit amount must be positive")
    return await append_entry(
        session,
        user_id=user_id,
        amount=-amount,
        kind=kind,
        reference=reference,
        extra=extra,
    )
