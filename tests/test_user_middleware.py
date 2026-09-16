import asyncio
from datetime import UTC, datetime

import pytest
from aiogram.types import CallbackQuery, Chat, Message, PreCheckoutQuery, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.op_gate import _chat_id, _should_skip
from app.bot.middlewares.runtime import RuntimeMiddleware
from app.bot.middlewares.throttle import ThrottleMiddleware
from app.bot.middlewares.user import UserMiddleware
from app.bot.middlewares.user_lock import UserLockMiddleware
from app.db.models import Base
from app.db.session import create_engine
from app.services import events
from app.services.access import AccessRegistry
from app.services.app_settings import RuntimeSettingsStore


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
async def test_user_middleware_sets_db_user_from_update_wrapping_message(session, settings) -> None:
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
async def test_user_middleware_sets_db_user_from_update_wrapping_callback(session, settings) -> None:
    update = Update(update_id=2, callback_query=_callback("home", user_id=8))
    middleware = UserMiddleware(settings)
    data: dict = {"session": session}

    result = await middleware(_passthrough, update, data)

    assert result["db_user"].id == 8


@pytest.mark.asyncio
async def test_user_middleware_sets_db_user_from_update_wrapping_pre_checkout(session, settings) -> None:
    update = Update(update_id=3, pre_checkout_query=_pre_checkout(user_id=9))
    middleware = UserMiddleware(settings)
    data: dict = {"session": session}

    result = await middleware(_passthrough, update, data)

    assert result["db_user"].id == 9


@pytest.mark.asyncio
async def test_user_middleware_clears_blocked_flag_when_user_returns(session, settings) -> None:
    middleware = UserMiddleware(settings)
    data: dict = {"session": session}
    result = await middleware(_passthrough, _message("/start", user_id=11), data)
    user = result["db_user"]
    user.blocked_bot_at = datetime.now(UTC)
    await session.flush()
    await middleware(_passthrough, _message("hi", user_id=11), {"session": session})
    assert user.blocked_bot_at is None


@pytest.mark.asyncio
async def test_update_middleware_chain_injects_session_and_dispatches_events(settings) -> None:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    dispatched: list[list[str]] = []

    async def dispatcher(pending, data):
        dispatched.append([event.name for event in pending])

    db_mw = DbSessionMiddleware(factory, dispatcher=dispatcher)
    user_mw = UserMiddleware(settings)
    captured: dict = {}

    async def handler(event, data):
        captured.update(data)
        events.emit(data["session"], "ping", x=1)
        return "ok"

    async def through_user(event, data):
        return await user_mw(handler, event, data)

    update = Update(update_id=10, message=_message("/start", user_id=99))
    result = await db_mw(through_user, update, {})

    assert result == "ok"
    assert captured.get("session") is not None
    assert captured["db_user"].id == 99
    assert dispatched == [["ping"]]

    async def failing(event, data):
        events.emit(data["session"], "never")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await db_mw(failing, update, {})
    assert dispatched == [["ping"]]  # nothing dispatched after rollback
    await engine.dispose()


def test_op_gate_skips_start_when_update_wraps_message(settings) -> None:
    update = Update(update_id=1, message=_message("/start"))
    assert _should_skip(update, settings) is True


def test_op_gate_skips_help_and_paysupport(settings) -> None:
    assert _should_skip(Update(update_id=1, message=_message("/help")), settings) is True
    assert _should_skip(Update(update_id=1, message=_message("/paysupport")), settings) is True


def test_op_gate_does_not_skip_regular_message_wrapped_in_update(settings) -> None:
    update = Update(update_id=1, message=_message("кабинет"))
    assert _should_skip(update, settings) is False


def test_op_gate_skips_op_callback_wrapped_in_update(settings) -> None:
    update = Update(update_id=1, callback_query=_callback("op:verify"))
    assert _should_skip(update, settings) is True
    assert _should_skip(Update(update_id=2, callback_query=_callback("admin:home")), settings) is True
    assert _should_skip(Update(update_id=3, callback_query=_callback("menu:daily")), settings) is False


def test_op_gate_chat_id_from_update_wrapping_message() -> None:
    update = Update(update_id=1, message=_message("/start", user_id=55))
    assert _chat_id(update, fallback=0) == 55


@pytest.mark.asyncio
async def test_throttle_middleware_blocks_bursts() -> None:
    calls: list[str] = []

    async def handler(event, data):
        calls.append("hit")
        return "ok"

    throttle = ThrottleMiddleware(interval=10.0)
    first = Update(update_id=1, message=_message("a", user_id=5))
    second = Update(update_id=2, message=_message("b", user_id=5))
    other = Update(update_id=3, message=_message("c", user_id=6))
    assert await throttle(handler, first, {}) == "ok"
    assert await throttle(handler, second, {}) is None
    assert await throttle(handler, other, {}) == "ok"
    assert calls == ["hit", "hit"]

    disabled = ThrottleMiddleware(interval=0)
    assert await disabled(handler, second, {}) == "ok"


@pytest.mark.asyncio
async def test_user_lock_serialises_same_user_and_parallelises_others() -> None:
    lock_mw = UserLockMiddleware()
    running: dict[int, int] = {}
    max_parallel: dict[int, int] = {}
    order: list[str] = []

    async def handler(event, data):
        user_id = event.message.from_user.id
        running[user_id] = running.get(user_id, 0) + 1
        max_parallel[user_id] = max(max_parallel.get(user_id, 0), running[user_id])
        order.append(f"start:{user_id}:{event.update_id}")
        await asyncio.sleep(0.02)
        running[user_id] -= 1
        order.append(f"end:{user_id}:{event.update_id}")
        return "ok"

    updates = [
        Update(update_id=1, message=_message("/start ref_1", user_id=5)),
        Update(update_id=2, message=_message("/start ref_1", user_id=5)),
        Update(update_id=3, message=_message("hi", user_id=6)),
    ]
    results = await asyncio.gather(*(lock_mw(handler, update, {}) for update in updates))
    assert results == ["ok", "ok", "ok"]
    assert max_parallel[5] == 1  # same user never overlaps
    assert order.index("end:5:1") < order.index("start:5:2")
    assert order.index("start:6:3") < order.index("end:5:1")  # other user ran in parallel
    assert lock_mw.active_locks == 0  # locks are released and cleaned up


@pytest.mark.asyncio
async def test_user_lock_skips_pre_checkout_and_releases_on_error() -> None:
    lock_mw = UserLockMiddleware()

    async def failing(event, data):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await lock_mw(failing, Update(update_id=1, message=_message("x", user_id=7)), {})
    assert lock_mw.active_locks == 0

    async def handler(event, data):
        return "ok"

    result = await lock_mw(handler, Update(update_id=2, pre_checkout_query=_pre_checkout(user_id=7)), {})
    assert result == "ok"
    assert lock_mw.active_locks == 0


@pytest.mark.asyncio
async def test_runtime_middleware_injects_settings_and_admin_flag(session, settings) -> None:
    access = AccessRegistry(frozenset({1}))
    store = RuntimeSettingsStore(settings)
    middleware = RuntimeMiddleware(store, access)

    result = await middleware(
        _passthrough, Update(update_id=1, message=_message("x", user_id=1)), {"session": session}
    )
    assert result["is_admin"] is True
    assert result["settings"].withdraw_min == settings.withdraw_min
    assert result["access"] is access

    result = await middleware(
        _passthrough, Update(update_id=2, message=_message("x", user_id=2)), {"session": session}
    )
    assert result["is_admin"] is False
