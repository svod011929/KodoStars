"""Embedded web server: Mini App page, health check and the verification callback."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.notify import Notifier
from app.config import Settings
from app.db.models import Base, DeviceCheck, User
from app.db.session import create_engine
from app.services import ledger, referrals
from app.services.access import AccessRegistry
from app.services.antifraud import bump_activity
from app.services.app_settings import RuntimeSettingsStore
from app.web.server import RateLimiter, WebServer, parse_init_data
from tests.fake_telegram import BOT_TOKEN, FakeSession, make_bot


def make_init_data(token: str, user_id: int, *, auth_date: int | None = None, tamper: bool = False) -> str:
    user = json.dumps(
        {"id": user_id, "first_name": "Tester", "username": f"user{user_id}"}, separators=(",", ":")
    )
    data = {"auth_date": str(auth_date or int(time.time())), "query_id": "AAEtest", "user": user}
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if tamper:
        signature = "0" * 64
    return urlencode({**data, "hash": signature})


class Harness:
    def __init__(self, client: TestClient, factory, tg: FakeSession, settings: Settings) -> None:
        self.client = client
        self.factory = factory
        self.tg = tg
        self.settings = settings

    async def post_device(self, user_id: int, fp: str, *, init_data: str | None = None, ip: str = "5.5.5.5"):
        payload = {
            "initData": init_data or make_init_data(BOT_TOKEN, user_id),
            "fingerprint": fp,
            "signals": {
                "ua": "Mozilla/5.0",
                "tg_platform": "android",
                "tg_version": "8.0",
                "screen": "1080x2400",
            },
        }
        return await self.client.post(
            "/api/device", json=payload, headers={"X-Forwarded-For": f"{ip}, 10.0.0.1"}
        )


@pytest.fixture
async def web() -> AsyncIterator[Harness]:
    settings = Settings(
        bot_token=BOT_TOKEN,
        admin_ids_raw="1",
        database_url="sqlite+aiosqlite://",
        signup_bonus=0,
        claim_cooldown_seconds=0,
        min_referral_activity=1,
        referral_min_piarflow_subs=0,
        web_public_url="https://mini.example",
    )
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    bot, tg = make_bot()
    access = AccessRegistry(settings.admin_ids)
    notifier = Notifier(bot, factory, access)
    server = WebServer(
        bot=bot,
        session_factory=factory,
        settings=settings,
        settings_store=RuntimeSettingsStore(settings),
        bot_username="kodostars_test_bot",
        events_sink=notifier.dispatch_events,
    )
    async with TestClient(TestServer(server.build_app())) as client:
        yield Harness(client, factory, tg, settings)
    await bot.session.close()
    await engine.dispose()


async def _seed_user(factory, user_id: int, referred_by: int | None = None) -> None:
    async with factory() as session:
        user = User(id=user_id, first_name=f"U{user_id}", referred_by_id=referred_by)
        session.add(user)
        await session.commit()


@pytest.mark.asyncio
async def test_static_routes(web: Harness) -> None:
    health = await web.client.get("/health")
    assert health.status == 200 and (await health.json())["status"] == "ok"
    landing = await web.client.get("/")
    assert landing.status == 200 and "kodostars_test_bot" in await landing.text()
    page = await web.client.get("/verify")
    body = await page.text()
    assert page.status == 200 and "telegram-web-app.js" in body and "/api/device" in body


def test_parse_init_data_validates_signature_and_age() -> None:
    parsed = parse_init_data(BOT_TOKEN, make_init_data(BOT_TOKEN, 42))
    assert parsed.user is not None and parsed.user.id == 42
    with pytest.raises(ValueError):
        parse_init_data(BOT_TOKEN, make_init_data(BOT_TOKEN, 42, tamper=True))
    with pytest.raises(ValueError, match="expired"):
        parse_init_data(BOT_TOKEN, make_init_data(BOT_TOKEN, 42, auth_date=int(time.time()) - 7 * 3600))
    with pytest.raises(ValueError):
        parse_init_data("other:token", make_init_data(BOT_TOKEN, 42))


@pytest.mark.asyncio
async def test_device_callback_rejects_bad_requests(web: Harness) -> None:
    await _seed_user(web.factory, 42)
    bad_json = await web.client.post("/api/device", data="nope", headers={"Content-Type": "application/json"})
    assert bad_json.status == 400
    forged = await web.post_device(42, "f" * 64, init_data=make_init_data(BOT_TOKEN, 42, tamper=True))
    assert forged.status == 401
    unknown = await web.post_device(777, "f" * 64)
    assert unknown.status == 404
    # A user cannot verify on behalf of somebody else: the id comes from the signature only.
    other_signed = await web.post_device(42, "f" * 64, init_data=make_init_data(BOT_TOKEN, 43))
    assert other_signed.status == 404


@pytest.mark.asyncio
async def test_verification_flow_pays_referrer_and_flags_twinks(web: Harness) -> None:
    await _seed_user(web.factory, 1)  # referrer
    await _seed_user(web.factory, 42)
    await _seed_user(web.factory, 43)
    async with web.factory() as session:
        for uid in (42, 43):
            user = await session.get(User, uid)
            await referrals.attach_referrer(session, user=user, payload="ref_1", settings=web.settings)
            await bump_activity(session, user, 1)
            # Activity is enough, but the device is not verified yet → no bonus.
            assert await referrals.activate_if_ready(session, user=user, settings=web.settings) == []
        await session.commit()

    first = await web.post_device(42, "c" * 64)
    assert first.status == 200
    assert await first.json() == {"ok": True, "twink": False, "first_time": True}
    async with web.factory() as session:
        user = await session.get(User, 42)
        assert user.device_verified_at is not None and user.referral_activated is True
        assert await ledger.get_balance(session, 1) == web.settings.referral_l1_bonus
        row = (await session.execute(select(DeviceCheck))).scalars().one()
        assert row.ip == "5.5.5.5" and row.platform == "android" and row.fp_hash == "c" * 64
    # The user got a confirmation, the referrer got the activation bonus notice.
    assert any("Устройство подтверждено" in text for text in web.tg.texts(42))
    assert any("активировался" in text for text in web.tg.texts(1))

    second = await web.post_device(43, "c" * 64)
    assert (await second.json())["twink"] is True
    async with web.factory() as session:
        twink = await session.get(User, 43)
        assert twink.twink_of == 42 and twink.referral_activated is False
        assert await ledger.get_balance(session, 1) == web.settings.referral_l1_bonus  # not paid twice
    assert any("другой аккаунт" in text for text in web.tg.texts(43))


@pytest.mark.asyncio
async def test_disabled_check_and_banned_user(web: Harness) -> None:
    await _seed_user(web.factory, 42)
    async with web.factory() as session:
        user = await session.get(User, 42)
        user.is_banned = True
        await session.commit()
    banned = await web.post_device(42, "d" * 64)
    assert banned.status == 403

    web.settings.device_check_enabled = False
    disabled = await web.post_device(42, "d" * 64)
    assert disabled.status == 404
    web.settings.device_check_enabled = True


def test_rate_limiter() -> None:
    limiter = RateLimiter(per_minute=3, max_keys=2)
    assert all(limiter.allow("a") for _ in range(3))
    assert limiter.allow("a") is False
    assert limiter.allow("b") and limiter.allow("c")  # eviction keeps the structure bounded
    assert limiter.allow("a")  # "a" was evicted → fresh window
