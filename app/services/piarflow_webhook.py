"""Handle PiarFlow unsubscribe webhooks: revoke OP cache and debit earned Stars."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerKind, PiarflowUnsub, User
from app.services import events, ledger
from app.services.antifraud import record_event
from app.services.errors import InsufficientFunds


@dataclass(slots=True, frozen=True)
class UnsubResult:
    processed: bool
    duplicate: bool
    penalty: int
    user_id: int | None


async def handle_unsubscribe(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    settings: Settings,
) -> UnsubResult:
    """Apply one unsubscribe event. Idempotent on ``(tg_user_id, offer_link)``."""
    if payload.get("test"):
        return UnsubResult(processed=False, duplicate=False, penalty=0, user_id=None)

    status = str(payload.get("status") or "").lower()
    if status and status != "unsubscribed":
        return UnsubResult(processed=False, duplicate=False, penalty=0, user_id=None)

    try:
        tg_user_id = int(payload["tg_user_id"])
    except (KeyError, TypeError, ValueError):
        return UnsubResult(processed=False, duplicate=False, penalty=0, user_id=None)

    offer_link = str(payload.get("offer_link") or "").strip()[:512] or "unknown"
    chat_id = _optional_int(payload.get("chat_id"))
    bot_id = _optional_int(payload.get("bot_id"))

    existing = await session.execute(
        select(PiarflowUnsub.id).where(
            PiarflowUnsub.tg_user_id == tg_user_id,
            PiarflowUnsub.offer_link == offer_link,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return UnsubResult(processed=False, duplicate=True, penalty=0, user_id=tg_user_id)

    row = PiarflowUnsub(
        tg_user_id=tg_user_id,
        offer_link=offer_link,
        chat_id=chat_id,
        bot_id=bot_id,
        penalty=0,
    )
    session.add(row)
    await session.flush()

    user = await session.get(User, tg_user_id)
    penalty = 0
    if user is not None:
        user.last_op_ok_at = None
        wanted = max(int(settings.piarflow_unsub_penalty), 0)
        if wanted > 0:
            balance = await ledger.get_balance(session, user.id)
            take = min(wanted, balance)
            if take > 0:
                try:
                    await ledger.debit(
                        session,
                        user_id=user.id,
                        amount=take,
                        kind=LedgerKind.UNSUB_PENALTY,
                        reference=f"piarflow:unsub:{row.id}",
                        extra={"offer_link": offer_link},
                    )
                    penalty = take
                except InsufficientFunds:
                    penalty = 0
        row.penalty = penalty
        await record_event(
            session,
            user_id=user.id,
            kind="piarflow_unsub",
            detail=f"offer={offer_link[:120]} penalty={penalty}",
        )
        events.emit(
            session,
            "piarflow_unsubscribed",
            user_id=user.id,
            offer_link=offer_link,
            penalty=penalty,
        )
    await session.flush()
    return UnsubResult(processed=True, duplicate=False, penalty=penalty, user_id=tg_user_id)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
