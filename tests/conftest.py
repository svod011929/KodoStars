import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.bot.factory import create_dispatcher, make_broadcast_sender
from app.bot.notify import Notifier
from app.config import Settings
from app.db.models import Base
from app.db.seed import seed_catalog
from app.db.session import create_engine
from app.op.gate import OpGate
from app.services.access import AccessRegistry
from app.services.app_settings import RuntimeSettingsStore
from app.services.broadcasts import BroadcastRunner
from app.services import gifts as gifts_service
from tests.fake_telegram import BOT_USERNAME, FakeSession, make_bot

ADMIN_ID = 1
USER_ID = 42
OTHER_ID = 43


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bot_token="000000000:PLACEHOLDER_TOKEN_REPLACE_ME",
        admin_ids_raw="1",
        database_url="sqlite+aiosqlite://",
        referral_levels=2,
        referral_l1_percent=15,
        referral_l2_percent=5,
        referral_l1_bonus=10,
        referral_l2_bonus=3,
        min_referral_activity=2,
        signup_bonus=0,
        claim_cooldown_seconds=0,
    )


@pytest.fixture
async def session(settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


@dataclass
class BotHarness:
    """One dispatcher per test module (aiogram routers attach to a single dispatcher);
    ``reset()`` gives every test a clean database, FSM storage and fake Telegram."""

    bot: Bot
    tg: FakeSession
    dp: Dispatcher
    settings: Settings
    engine: AsyncEngine
    factory: async_sessionmaker[AsyncSession]
    access: AccessRegistry
    store: RuntimeSettingsStore
    runner: BroadcastRunner

    async def feed(self, update: Update) -> None:
        await self.dp.feed_update(self.bot, update)

    async def reset(self) -> None:
        await self.runner.shutdown()
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with self.factory() as db:
            await seed_catalog(db)
            await self.access.load(db)
        self.store.invalidate()
        self.settings.web_public_url = ""  # device check off unless a test enables it
        self.dp.storage.storage.clear()  # MemoryStorage
        self.tg.clear()
        self.tg.member_status.clear()
        self.tg.fail_refunds = False
        self.tg.fail_send_gift = False
        gifts_service.invalidate_cache()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def harness() -> AsyncIterator[BotHarness]:
    tmp_dir = Path(tempfile.mkdtemp(prefix="kodostars-e2e-"))
    settings = Settings(
        bot_token="123456789:TEST-TOKEN-FOR-TESTS",
        admin_ids_raw=str(ADMIN_ID),
        database_url=f"sqlite+aiosqlite:///{(tmp_dir / 'e2e.db').as_posix()}",
        signup_bonus=5,
        claim_cooldown_seconds=0,
        throttle_seconds=0,
        piarflow_enabled=False,
        withdraw_cooldown_hours=0,
    )
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        await seed_catalog(db)

    bot, tg = make_bot()
    access = AccessRegistry(settings.admin_ids)
    async with factory() as db:
        await access.load(db)
    store = RuntimeSettingsStore(settings)
    notifier = Notifier(bot, factory, access)
    runner = BroadcastRunner(
        factory,
        sender=make_broadcast_sender(bot),
        rate_per_sec=1000,
        progress_every=2,
        progress_callback=notifier.broadcast_progress,
    )
    dp = create_dispatcher(
        settings,
        factory,
        OpGate(settings),
        access=access,
        settings_store=store,
        notifier=notifier,
        broadcast_runner=runner,
        bot_username=BOT_USERNAME,
    )
    yield BotHarness(
        bot=bot,
        tg=tg,
        dp=dp,
        settings=settings,
        engine=engine,
        factory=factory,
        access=access,
        store=store,
        runner=runner,
    )
    await runner.shutdown()
    await bot.session.close()
    await engine.dispose()
