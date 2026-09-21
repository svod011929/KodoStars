"""Device/twink gating before PiarFlow + unsubscribe webhook penalties."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Base, LedgerKind, User
from app.db.session import create_engine
from app.services import devices, ledger, piarflow_webhook
from app.services.app_settings import RuntimeSettingsStore
from app.web.server import WebServer
from tests.fake_telegram import make_bot


def _settings(**overrides) -> Settings:
    base = dict(
        bot_token="123:ABC",
        admin_ids_raw="1",
        database_url="sqlite+aiosqlite://",
        web_public_url="https://example.test",
        device_check_enabled=True,
        device_check_for_op=True,
        twink_block_op=True,
        piarflow_unsub_penalty=7,
    )
    base.update(overrides)
    return Settings(**base)


async def _user(session: AsyncSession, uid: int, **extra) -> User:
    user = User(id=uid, first_name=f"U{uid}", username=f"user{uid}", **extra)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_op_access_requires_device_before_piarflow(session) -> None:
    settings = _settings()
    user = await _user(session, 10)
    assert devices.op_access_block_reason(user, settings) == "device"
    user.device_verified_at = datetime.now(UTC)
    assert devices.op_access_block_reason(user, settings) is None


@pytest.mark.asyncio
async def test_op_access_blocks_twinks(session) -> None:
    settings = _settings()
    first = await _user(session, 20)
    first.device_verified_at = datetime.now(UTC)
    twin = await _user(session, 21, twink_of=20)
    twin.device_verified_at = datetime.now(UTC)
    assert devices.op_access_block_reason(twin, settings) == "twink"
    twin.is_trusted = True
    assert devices.op_access_block_reason(twin, settings) is None


@pytest.mark.asyncio
async def test_unsubscribe_webhook_penalizes_and_is_idempotent(session) -> None:
    settings = _settings()
    user = await _user(session, 30)
    user.last_op_ok_at = datetime.now(UTC)
    await ledger.credit(session, user_id=user.id, amount=20, kind=LedgerKind.TASK)
    payload = {
        "tg_user_id": 30,
        "offer_link": "https://t.me/sponsor",
        "status": "unsubscribed",
        "chat_id": -1001,
        "bot_id": 1,
    }
    first = await piarflow_webhook.handle_unsubscribe(session, payload=payload, settings=settings)
    assert first.processed and first.penalty == 7
    await session.refresh(user)
    assert user.last_op_ok_at is None
    assert await ledger.get_balance(session, user.id) == 13

    second = await piarflow_webhook.handle_unsubscribe(session, payload=payload, settings=settings)
    assert second.duplicate and not second.processed
    assert await ledger.get_balance(session, user.id) == 13


@pytest.mark.asyncio
async def test_unsubscribe_webhook_http_endpoint() -> None:
    settings = _settings()
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = User(id=40, first_name="A", username="a", last_op_ok_at=datetime.now(UTC), balance=0)
        session.add(user)
        await ledger.credit(session, user_id=40, amount=5, kind=LedgerKind.DAILY)
        await session.commit()

    bot, _tg = make_bot()
    server = WebServer(
        bot=bot,
        session_factory=factory,
        settings=settings,
        settings_store=RuntimeSettingsStore(settings),
        bot_username="bot",
    )
    app = server.build_app()
    # aiohttp test client style without pytest-aiohttp: call handler directly.
    request = _FakeRequest(
        {"tg_user_id": 40, "offer_link": "https://t.me/x", "status": "unsubscribed", "test": False}
    )
    request.app = app
    # Bind limiter state via server method.
    response = await server.piarflow_webhook(request)  # type: ignore[arg-type]
    assert response.status == 200
    body = response.body
    assert b'"ok": true' in body or b'"ok":true' in body

    async with factory() as session:
        user = await session.get(User, 40)
        assert user is not None and user.last_op_ok_at is None
        assert await ledger.get_balance(session, 40) == 0

    await engine.dispose()


class _FakeRequest:
    """Minimal stand-in for aiohttp.web.Request used by the webhook handler."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.remote = "127.0.0.1"
        self.app = web.Application()

    async def json(self):
        return self._payload
