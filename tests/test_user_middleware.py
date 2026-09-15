from datetime import UTC, datetime

import pytest
from aiogram.types import CallbackQuery, Chat, Message, PreCheckoutQuery, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.op_gate import _chat_id, _should_skip
from app.bot.middlewares.user import UserMiddleware
from app.db.models import Base
from app.db.session import create_engine


def _tg_user(user_id: int = 42) -> TgUser:
    return TgUser(id=user_id, is_bot=False, first_name="Daniel", username="daniel")


def _message(text: str = "/start", user_id: int = 42) -> Message:
    user = _tg_user(user_id)
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=user,
        text=text,
    )


def _callback(data: str = "home", user_id: int = 42) -> CallbackQuery:
    message = _message("menu", user_id=user_id)
    return CallbackQuery(
        id="cb1",
        from_user=_tg_user(user_id),
        chat_instance="chat-instance",
        data=data,
        message=message,
    )


def _pre_checkout(user_id: int = 42) -> PreCheckoutQuery:
    return PreCheckoutQuery(
        id="pcq1",
        from_user=_tg_user(user_id),
        currency="XTR",
        total_amount=10,
        invoice_payload="boost:1",
    )


async def _passthrough(event, data):
    return data


@pytest.mark.asyncio
async def test_user_middleware_sets_db_user_from_update_wrapping_message(
    session, settings
) -> None:
    message = _message("/start", user_id=42)
    update = Update(update_id=1, message=message)
    middleware = UserMiddleware(settings)
    data: dict = {"session": session}

    result = await middleware(_passthrough, update, data)

    assert "db_user" in result
    assert result["db_user"].id == 42
    assert result["user_created"] is True


@pytest.mark.asyncio
async def test_user_middleware_sets_db_user_from_bare_message(session, settings) -> None:
    message = _message("/start", user_id=7)
    middleware = UserMiddleware(settings)
    data: dict = {"session": session}

    result = await middleware(_passthrough, message, data)

    assert result["db_user"].id == 7


@pytest.mark.asyncio
async def test_user_middleware_sets_db_user_from_update_wrapping_callback(
    session, settings
) -> None:
    update = Update(update_id=2, callback_query=_callback("home", user_id=8))
    middleware = UserMiddleware(settings)
    data: dict = {"session": session}

    result = await middleware(_passthrough, update, data)

    assert result["db_user"].id == 8


@pytest.mark.asyncio
async def test_user_middleware_sets_db_user_from_update_wrapping_pre_checkout(
    session, settings
) -> None:
    update = Update(update_id=3, pre_checkout_query=_pre_checkout(user_id=9))
    middleware = UserMiddleware(settings)
    data: dict = {"session": session}

    result = await middleware(_passthrough, update, data)

    assert result["db_user"].id == 9


@pytest.mark.asyncio
async def test_update_middleware_chain_injects_session_and_db_user(settings) -> None:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    db_mw = DbSessionMiddleware(factory)
    user_mw = UserMiddleware(settings)
    captured: dict = {}

    async def handler(event, data):
        captured.update(data)
        return "ok"

    async def through_user(event, data):
        return await user_mw(handler, event, data)

    update = Update(update_id=10, message=_message("/start", user_id=99))
    result = await db_mw(through_user, update, {})
    await engine.dispose()

    assert result == "ok"
    assert captured.get("session") is not None
    assert captured["db_user"].id == 99


def test_op_gate_skips_start_when_update_wraps_message(settings) -> None:
    update = Update(update_id=1, message=_message("/start"))
    assert _should_skip(update, settings) is True


def test_op_gate_does_not_skip_regular_message_wrapped_in_update(settings) -> None:
    update = Update(update_id=1, message=_message("кабинет"))
    assert _should_skip(update, settings) is False


def test_op_gate_skips_op_callback_wrapped_in_update(settings) -> None:
    update = Update(update_id=1, callback_query=_callback("op:verify"))
    assert _should_skip(update, settings) is True


def test_op_gate_chat_id_from_update_wrapping_message() -> None:
    update = Update(update_id=1, message=_message("/start", user_id=55))
    assert _chat_id(update, fallback=0) == 55
