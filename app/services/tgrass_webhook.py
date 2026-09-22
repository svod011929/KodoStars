"""Tgrass webhooks: unsubscribe penalty + task-complete ack.

Docs: https://tgrass.space/integration (Настройки бота → Webhook).

Configure in @tgrassbot:

* Webhook отписки → ``{WEB_PUBLIC_URL}/api/tgrass/unsubscribe``
* Webhook задания → ``{WEB_PUBLIC_URL}/api/tgrass/webhook``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerKind, TgrassUnsub, User
from app.services import events, ledger
from app.services.antifraud import record_event
from app.services.errors import InsufficientFunds


@dataclass(slots=True, frozen=True)
class TgrassWebhookResult:
    kind: str  # "unsub" | "task" | "ignored" | "test"
    processed: bool
    duplicate: bool = False
    penalty: int = 0
    user_id: int | None = None


async def handle_webhook(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    settings: Settings,
) -> TgrassWebhookResult:
    if payload.get("test"):
        return TgrassWebhookResult(kind="test", processed=False)

    status = str(payload.get("status") or "").lower()
    if status == "unsubscribed":
        return await _handle_unsub(session, payload=payload, settings=settings)

    if payload.get("offer_id") is not None and payload.get("tg_user_id") is not None:
        return await _handle_task(session, payload=payload)

    return TgrassWebhookResult(kind="ignored", processed=False)


async def _handle_task(session: AsyncSession, *, payload: dict[str, Any]) -> TgrassWebhookResult:
    """Task-complete webhook: acknowledge only (OP re-check happens in-bot)."""
    try:
        tg_user_id = int(payload["tg_user_id"])
    except (KeyError, TypeError, ValueError):
        return TgrassWebhookResult(kind="task", processed=False)
    offer_link = str(payload.get("offer_link") or "").strip()[:512]
    await record_event(
        session,
        user_id=tg_user_id,
        kind="tgrass_task",
        detail=f"offer_id={payload.get('offer_id')} link={offer_link[:80]}",
    )
    return TgrassWebhookResult(kind="task", processed=True, user_id=tg_user_id)


async def _handle_unsub(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    settings: Settings,
) -> TgrassWebhookResult:
    try:
        tg_user_id = int(payload["tg_user_id"])
    except (KeyError, TypeError, ValueError):
        return TgrassWebhookResult(kind="unsub", processed=False)

    offer_link = str(payload.get("offer_link") or "").strip()[:512] or "unknown"

    existing = await session.execute(
        select(TgrassUnsub.id).where(
            TgrassUnsub.tg_user_id == tg_user_id,
            TgrassUnsub.offer_link == offer_link,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return TgrassWebhookResult(
            kind="unsub", processed=False, duplicate=True, user_id=tg_user_id
        )

    row = TgrassUnsub(tg_user_id=tg_user_id, offer_link=offer_link, penalty=0)
    session.add(row)
    await session.flush()

    user = await session.get(User, tg_user_id)
    penalty = 0
    if user is not None:
        user.last_op_ok_at = None
        wanted = max(int(settings.tgrass_unsub_penalty), 0)
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
                        reference=f"tgrass:unsub:{row.id}",
                        extra={"offer_link": offer_link},
                    )
                    penalty = take
                except InsufficientFunds:
                    penalty = 0
        row.penalty = penalty
        await record_event(
            session,
            user_id=user.id,
            kind="tgrass_unsub",
            detail=f"offer={offer_link[:120]} penalty={penalty}",
        )
        events.emit(
            session,
            "tgrass_unsubscribed",
            user_id=user.id,
            offer_link=offer_link,
            penalty=penalty,
        )
    await session.flush()
    return TgrassWebhookResult(
        kind="unsub", processed=True, duplicate=False, penalty=penalty, user_id=tg_user_id
    )
