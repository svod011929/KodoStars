"""Append-only ledger with an atomically maintained ``users.balance``.

Every balance change is a single ``UPDATE ... SET balance = balance + :delta``
guarded by ``balance + :delta >= 0`` (unless ``allow_negative``). The returned
balance is stored as ``balance_after`` on the ledger row, so the journal and the
denormalized column can never drift under concurrent updates.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry, LedgerKind, User
from app.services.errors import InsufficientFunds, NotFound


async def get_balance(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(select(User.balance).where(User.id == user_id))
    value = result.scalar_one_or_none()
    return int(value or 0)


async def ledger_sum(session: AsyncSession, user_id: int) -> int:
    """Sum of all ledger rows — used by the reconciliation tool, not by hot paths."""
    result = await session.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.user_id == user_id)
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

    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(balance=User.balance + amount)
        .returning(User.balance)
        .execution_options(synchronize_session="fetch")
    )
    if amount < 0 and not allow_negative:
        stmt = stmt.where(User.balance + amount >= 0)

    next_balance = (await session.execute(stmt)).scalar_one_or_none()
    if next_balance is None:
        exists = await session.execute(select(User.id).where(User.id == user_id))
        if exists.scalar_one_or_none() is None:
            raise NotFound("Пользователь не найден")
        raise InsufficientFunds("Недостаточно Stars на балансе")

    entry = LedgerEntry(
        user_id=user_id,
        amount=amount,
        balance_after=int(next_balance),
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
    allow_negative: bool = False,
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
        allow_negative=allow_negative,
    )


async def history(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[LedgerEntry]:
    result = await session.execute(
        select(LedgerEntry)
        .where(LedgerEntry.user_id == user_id)
        .order_by(LedgerEntry.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_entries(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(LedgerEntry).where(LedgerEntry.user_id == user_id)
    )
    return int(result.scalar_one())


async def reconcile(session: AsyncSession, *, limit: int = 20) -> list[tuple[int, int, int]]:
    """Return ``(user_id, balance, ledger_sum)`` for users whose balance drifted."""
    sums = (
        select(
            LedgerEntry.user_id.label("uid"),
            func.coalesce(func.sum(LedgerEntry.amount), 0).label("total"),
        )
        .group_by(LedgerEntry.user_id)
        .subquery()
    )
    stmt = (
        select(User.id, User.balance, func.coalesce(sums.c.total, 0))
        .outerjoin(sums, sums.c.uid == User.id)
        .where(User.balance != func.coalesce(sums.c.total, 0))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(int(uid), int(balance), int(total)) for uid, balance, total in result.all()]
