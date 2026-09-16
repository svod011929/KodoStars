"""A fake aiogram session: records every Bot API call and returns plausible results.

Lets tests drive the real dispatcher (middlewares, routers, FSM) end to end
without touching Telegram.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import (
    AnswerCallbackQuery,
    AnswerPreCheckoutQuery,
    CopyMessage,
    CreateChatInviteLink,
    CreateChatSubscriptionInviteLink,
    EditMessageText,
    GetChatMember,
    GetMe,
    GetMyStarBalance,
    RefundStarPayment,
    SendDocument,
    SendInvoice,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatInviteLink,
    ChatMemberAdministrator,
    ChatMemberLeft,
    ChatMemberMember,
    Message,
    MessageId,
    MessageOriginChannel,
    PreCheckoutQuery,
    StarAmount,
    SuccessfulPayment,
    Update,
)
from aiogram.types import User as TgUser

from app.bot.request_middleware import install_request_middlewares

BOT_TOKEN = "123456789:TEST-TOKEN-FOR-TESTS"
BOT_ID = 123456789
BOT_USERNAME = "kodostars_test_bot"


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.member_status: dict[tuple[str, int], str] = {}
        self.fail_refunds = False
        self._message_id = 1000

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""

    def next_message_id(self) -> int:
        self._message_id += 1
        return self._message_id

    def bot_user(self) -> TgUser:
        return TgUser(id=BOT_ID, is_bot=True, first_name="KodoStars", username=BOT_USERNAME)

    def sent(self, kind: type[TelegramMethod[Any]] | None = None) -> list[TelegramMethod[Any]]:
        if kind is None:
            return list(self.requests)
        return [request for request in self.requests if isinstance(request, kind)]

    def texts(self, chat_id: int | None = None) -> list[str]:
        out: list[str] = []
        for request in self.requests:
            if not isinstance(request, (SendMessage, EditMessageText)):
                continue
            if chat_id is None or request.chat_id == chat_id:
                out.append(request.text)
        return out

    def last_text(self, chat_id: int | None = None) -> str:
        texts = self.texts(chat_id)
        return texts[-1] if texts else ""

    def alerts(self) -> list[str]:
        return [request.text or "" for request in self.sent(AnswerCallbackQuery)]

    def clear(self) -> None:
        self.requests.clear()

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 - signature dictated by aiogram BaseSession
    ) -> Any:
        self.requests.append(method)
        return self._respond(method)

    def _message(self, chat_id: int | str, text: str | None = None, message_id: int | None = None) -> Message:
        return Message(
            message_id=message_id or self.next_message_id(),
            date=datetime.now(UTC),
            chat=Chat(id=int(chat_id), type="private"),
            from_user=self.bot_user(),
            text=text,
        )

    def _respond(self, method: TelegramMethod[Any]) -> Any:
        if isinstance(method, GetMe):
            return self.bot_user()
        if isinstance(method, SendMessage):
            return self._message(method.chat_id, method.text)
        if isinstance(method, EditMessageText):
            return self._message(method.chat_id or 0, method.text, message_id=method.message_id)
        if isinstance(method, (SendInvoice, SendDocument)):
            return self._message(method.chat_id, "invoice")
        if isinstance(method, CopyMessage):
            return MessageId(message_id=self.next_message_id())
        if isinstance(method, GetChatMember):
            status = self.member_status.get((str(method.chat_id), method.user_id), "member")
            user = TgUser(id=method.user_id, is_bot=False, first_name="U")
            if status == "left":
                return ChatMemberLeft(user=user)
            if status == "administrator":
                # Handlers only read ``.status``; skip validation of the many permission flags.
                return ChatMemberAdministrator.model_construct(status="administrator", user=user)
            return ChatMemberMember(user=user)
        if isinstance(method, GetMyStarBalance):
            return StarAmount(amount=321)
        if isinstance(method, (CreateChatInviteLink, CreateChatSubscriptionInviteLink)):
            price = getattr(method, "subscription_price", None)
            suffix = f"generated{price}" if price else "generatedFree"
            return ChatInviteLink(
                invite_link=f"https://t.me/+{suffix}",
                creator=self.bot_user(),
                creates_join_request=False,
                is_primary=False,
                is_revoked=False,
                name=method.name,
                subscription_price=price,
            )
        if isinstance(method, RefundStarPayment):
            return not self.fail_refunds
        if isinstance(method, AnswerPreCheckoutQuery):
            return True
        return True


def make_bot() -> tuple[Bot, FakeSession]:
    session = FakeSession()
    bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return install_request_middlewares(bot), session


def tg_user(user_id: int, *, username: str | None = None, first_name: str = "Daniel") -> TgUser:
    return TgUser(id=user_id, is_bot=False, first_name=first_name, username=username or f"user{user_id}")


_update_id = 0


def _next_update_id() -> int:
    global _update_id
    _update_id += 1
    return _update_id


def message_update(user_id: int, text: str, *, message_id: int = 1, **kwargs: Any) -> Update:
    message = Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=tg_user(user_id),
        text=text,
        **kwargs,
    )
    return Update(update_id=_next_update_id(), message=message)


def forwarded_channel_post_update(
    user_id: int, *, chat_id: int, title: str, username: str | None = None
) -> Update:
    """A post forwarded from a channel into the bot (admin adds a channel this way)."""
    origin = MessageOriginChannel(
        type="channel",
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="channel", title=title, username=username),
        message_id=77,
    )
    message = Message(
        message_id=_next_update_id(),
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=tg_user(user_id),
        text="forwarded post",
        forward_origin=origin,
    )
    return Update(update_id=_next_update_id(), message=message)


def callback_update(user_id: int, data: str, *, message_id: int = 1) -> Update:
    message = Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=BOT_ID, is_bot=True, first_name="KodoStars", username=BOT_USERNAME),
        text="screen",
    )
    query = CallbackQuery(
        id=f"cb{_next_update_id()}",
        from_user=tg_user(user_id),
        chat_instance="ci",
        data=data,
        message=message,
    )
    return Update(update_id=_next_update_id(), callback_query=query)


def pre_checkout_update(user_id: int, payload: str, amount: int) -> Update:
    query = PreCheckoutQuery(
        id=f"pcq{_next_update_id()}",
        from_user=tg_user(user_id),
        currency="XTR",
        total_amount=amount,
        invoice_payload=payload,
    )
    return Update(update_id=_next_update_id(), pre_checkout_query=query)


def successful_payment_update(user_id: int, payload: str, amount: int, charge_id: str) -> Update:
    payment = SuccessfulPayment(
        currency="XTR",
        total_amount=amount,
        invoice_payload=payload,
        telegram_payment_charge_id=charge_id,
        provider_payment_charge_id=f"prov_{charge_id}",
    )
    message = Message(
        message_id=_next_update_id(),
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=tg_user(user_id),
        successful_payment=payment,
    )
    return Update(update_id=_next_update_id(), message=message)
