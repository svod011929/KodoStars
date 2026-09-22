"""Turn committed domain events into Telegram notifications (best-effort)."""

from __future__ import annotations

from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot import emoji as pe
from app.bot import texts
from app.bot.admin import keyboards as admin_keyboards
from app.bot.admin import texts as admin_texts
from app.db.models import Broadcast, User, Withdrawal
from app.services import ledger, referrals
from app.services.access import AccessRegistry
from app.services.app_settings import RuntimeSettingsStore
from app.services.events import DomainEvent

log = structlog.get_logger("kodostars.notify")


class Notifier:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker,
        access: AccessRegistry,
        settings_store: RuntimeSettingsStore | None = None,
    ) -> None:
        self._bot = bot
        self._factory = session_factory
        self._access = access
        self._settings_store = settings_store

    async def dispatch(self, events: list[DomainEvent], data: dict[str, Any]) -> None:
        for event in events:
            try:
                await self._handle(event)
            except TelegramAPIError as exc:
                log.info("notify_skipped", event=event.name, error=str(exc))
            except Exception:
                log.warning("notify_failed", event=event.name, exc_info=True)

    async def _send(self, chat_id: int, text: str, **kwargs: Any) -> None:
        try:
            await self._bot.send_message(chat_id, pe.premiumize(text), disable_web_page_preview=True, **kwargs)
        except TelegramAPIError as exc:
            log.info("notify_send_failed", chat_id=chat_id, error=str(exc))

    async def broadcast_progress(self, row: Broadcast, chat_id: int, message_id: int) -> None:
        """Keep the admin's progress card fresh while a broadcast runs."""
        try:
            await self._bot.edit_message_text(
                admin_texts.broadcast_progress(row),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=admin_keyboards.broadcast_progress(row, row.status == "running"),
            )
        except TelegramAPIError as exc:
            if "message is not modified" not in str(exc).lower():
                log.info("broadcast_progress_edit_failed", error=str(exc))

    async def dispatch_events(self, events: list[DomainEvent]) -> None:
        """Entry point for producers outside an update (web server)."""
        await self.dispatch(events, {})

    async def _handle(self, event: DomainEvent) -> None:
        payload = event.payload
        match event.name:
            case "device_verified":
                await self._send(
                    payload["user_id"],
                    texts.notify_device_verified(bool(payload.get("twink")), bool(payload.get("first_time"))),
                    reply_markup=texts.home_button(),
                )
            case "piarflow_unsubscribed":
                await self._send(
                    payload["user_id"],
                    texts.notify_piarflow_unsubscribed(int(payload.get("penalty") or 0)),
                )
            case "referral_joined":
                await self._send(
                    payload["referrer_id"], texts.notify_referral_joined(payload["referee_name"])
                )
            case "referral_activated":
                await self._send(
                    payload["referrer_id"],
                    texts.notify_referral_activated(
                        payload["referee_name"], payload["level"], payload["amount"]
                    ),
                )
            case "task_completed":
                await self._send(
                    payload["user_id"], texts.notify_task_completed(payload["title"], payload["amount"])
                )
            case "withdrawal_created":
                await self._withdrawal_created(payload["withdrawal_id"])
            case "withdrawal_status":
                await self._withdrawal_status(payload)
                if payload.get("status") == "sent":
                    await self._payout_log(int(payload["withdrawal_id"]))
            case "withdrawal_cancelled":
                await self._withdrawal_cancelled(payload["withdrawal_id"])
            case "balance_adjusted":
                await self._send(
                    payload["user_id"],
                    texts.notify_balance_adjusted(payload["amount"], payload.get("reason", "")),
                )
            case "payment_refunded":
                await self._send(
                    payload["user_id"],
                    texts.notify_refund(
                        payload["xtr_amount"], payload["revoked_stars"], payload["product_title"]
                    ),
                )
            case "admin_alert":
                for admin_id in self._access.all_admin_ids():
                    await self._send(admin_id, payload["text"])
            case _:
                log.debug("notify_unknown_event", event=event.name)

    async def _payout_log(self, withdrawal_id: int) -> None:
        """Post completed payout to the configured public log channel (if any)."""
        if self._settings_store is None:
            return
        async with self._factory() as session:
            settings = await self._settings_store.effective(session)
            chat_id = int(settings.payout_log_chat_id or 0)
            if not chat_id:
                return
            wd = await session.get(Withdrawal, withdrawal_id)
            if wd is None:
                return
            user = await session.get(User, wd.user_id)
            if user is None:
                return
            text = admin_texts.payout_log_post(wd, user)
        await self._send(chat_id, text)

    async def _withdrawal_created(self, withdrawal_id: int) -> None:
        async with self._factory() as session:
            wd = await session.get(Withdrawal, withdrawal_id)
            if wd is None:
                return
            user = await session.get(User, wd.user_id)
            if user is None:
                return
            balance = await ledger.get_balance(session, user.id)
            refs = await referrals.referral_stats(session, user.id)
            activated = await referrals.activated_invite_count(session, user.id)
            text = admin_texts.withdrawal_alert(wd, user, balance, refs, activated)
        for admin_id in self._access.all_admin_ids():
            await self._send(
                admin_id,
                text,
                reply_markup=admin_keyboards.withdrawal_actions(wd.id, wd.status),
            )

    async def _withdrawal_status(self, payload: dict[str, Any]) -> None:
        async with self._factory() as session:
            wd = await session.get(Withdrawal, payload["withdrawal_id"])
            if wd is None:
                return
        await self._send(
            payload["user_id"],
            texts.withdraw_status_update(wd, payload["status"], payload.get("note") or ""),
        )

    async def _withdrawal_cancelled(self, withdrawal_id: int) -> None:
        async with self._factory() as session:
            wd = await session.get(Withdrawal, withdrawal_id)
            if wd is None:
                return
            user = await session.get(User, wd.user_id)
        name = user.display_name if user else str(wd.user_id)
        for admin_id in self._access.all_admin_ids():
            await self._send(admin_id, admin_texts.withdrawal_cancelled_alert(wd, name))
