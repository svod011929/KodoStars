"""CSV exports for the admin panel (UTF-8 with BOM so Excel opens them correctly)."""

import csv
from collections.abc import Iterable
from io import StringIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry, Payment, User, Withdrawal

EXPORT_LIMIT = 50_000


def _to_csv(header: list[str], rows: Iterable[Iterable[object]]) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue().encode("utf-8-sig")


def _iso(value) -> str:
    return value.isoformat(timespec="seconds") if value is not None else ""


async def users_csv(session: AsyncSession) -> bytes:
    result = await session.execute(select(User).order_by(User.id).limit(EXPORT_LIMIT))
    rows = (
        (
            u.id,
            u.username or "",
            u.first_name,
            u.balance,
            u.level,
            u.xp,
            u.streak,
            u.activity_score,
            u.referred_by_id or "",
            int(u.referral_activated),
            int(u.is_banned),
            int(u.blocked_bot_at is not None),
            _iso(u.created_at),
            _iso(u.last_action_at),
        )
        for u in result.scalars()
    )
    return _to_csv(
        [
            "id",
            "username",
            "first_name",
            "balance",
            "level",
            "xp",
            "streak",
            "activity",
            "referred_by",
            "activated",
            "banned",
            "blocked_bot",
            "created_at",
            "last_action_at",
        ],
        rows,
    )


async def withdrawals_csv(session: AsyncSession) -> bytes:
    result = await session.execute(select(Withdrawal).order_by(Withdrawal.id).limit(EXPORT_LIMIT))
    rows = (
        (
            w.id,
            w.user_id,
            w.amount,
            w.gift_id or "",
            w.gift_emoji or "",
            w.status,
            w.reviewed_by or "",
            _iso(w.created_at),
            _iso(w.reviewed_at),
            _iso(w.sent_at),
            (w.admin_note or "").replace("\n", " "),
        )
        for w in result.scalars()
    )
    return _to_csv(
        [
            "id",
            "user_id",
            "amount",
            "gift_id",
            "gift_emoji",
            "status",
            "reviewed_by",
            "created_at",
            "reviewed_at",
            "sent_at",
            "note",
        ],
        rows,
    )


async def ledger_csv(session: AsyncSession, *, user_id: int | None = None) -> bytes:
    stmt = select(LedgerEntry).order_by(LedgerEntry.id).limit(EXPORT_LIMIT)
    if user_id is not None:
        stmt = stmt.where(LedgerEntry.user_id == user_id)
    result = await session.execute(stmt)
    rows = (
        (e.id, e.user_id, e.amount, e.balance_after, e.kind, e.reference or "", _iso(e.created_at))
        for e in result.scalars()
    )
    return _to_csv(["id", "user_id", "amount", "balance_after", "kind", "reference", "created_at"], rows)


async def payments_csv(session: AsyncSession) -> bytes:
    result = await session.execute(select(Payment).order_by(Payment.id).limit(EXPORT_LIMIT))
    rows = (
        (
            p.id,
            p.user_id,
            p.product_id or "",
            p.xtr_amount,
            p.status,
            p.telegram_charge_id,
            _iso(p.created_at),
            _iso(p.refunded_at),
        )
        for p in result.scalars()
    )
    return _to_csv(
        ["id", "user_id", "product_id", "xtr", "status", "charge_id", "created_at", "refunded_at"],
        rows,
    )
