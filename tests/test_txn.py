"""Transactions must not span network I/O (regression for «database is locked»)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.methods import SendMessage, TelegramMethod
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.user import UserMiddleware
from app.bot.request_middleware import install_request_middlewares
from app.config import Settings
from app.db.models import Base, User
from app.db.session import create_engine
from app.db.txn import bind_session, commit_before_io, current_session, unbind_session
from tests.fake_telegram import BOT_TOKEN, FakeSession, make_bot, message_update


class SlowTelegram(FakeSession):
    """Telegram that takes ``delay`` seconds to deliver a message."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:  # noqa: ASYNC109
        if isinstance(method, SendMessage):
            await asyncio.sleep(self.delay)
        return await super().make_request(bot, method, timeout)


@pytest.mark.asyncio
async def test_commit_before_io_commits_pending_writes(settings) -> None:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    assert await commit_before_io() is False  # nothing bound
    async with factory() as session:
        token = bind_session(session)
        try:
            assert current_session() is session
            session.add(User(id=1, first_name="A"))
            await session.flush()
            assert await commit_before_io() is True
            assert session.in_transaction() is False
            assert await commit_before_io() is False  # nothing left to commit
            # Committed → visible through a different session/connection.
            async with factory() as other:
                assert (await other.get(User, 1)) is not None
        finally:
            unbind_session(token)
        assert current_session() is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_request_middleware_commits_before_telegram_call(settings) -> None:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    bot, tg = make_bot()

    async with factory() as session:
        token = bind_session(session)
        try:
            session.add(User(id=2, first_name="B"))
            await session.flush()
            await bot.get_me()
            assert session.in_transaction() is False
        finally:
            unbind_session(token)
    async with factory() as other:
        assert (await other.get(User, 2)) is not None
    assert len(tg.requests) == 1
    await bot.session.close()
    await engine.dispose()


async def _run_two_users(tmp_path: Path, *, commit_hook: bool) -> None:
    settings = Settings(
        admin_ids_raw="1",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'locked.db').as_posix()}",
        signup_bonus=0,
    )
    engine = create_engine(settings, busy_timeout_ms=100)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    bot = Bot(
        token=BOT_TOKEN, session=SlowTelegram(0.8), default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    if commit_hook:
        install_request_middlewares(bot)

    db_mw = DbSessionMiddleware(factory)
    user_mw = UserMiddleware(settings)

    async def handler(event, data):
        # The incident shape: a row was written (UserMiddleware upsert), then the
        # handler waits on Telegram while another user's update needs the write lock.
        await bot.send_message(event.message.from_user.id, "hi")
        return "ok"

    async def through_user(event, data):
        return await user_mw(handler, event, data)

    async def process(user_id: int, delay: float) -> str:
        await asyncio.sleep(delay)
        return await db_mw(through_user, message_update(user_id, "/start"), {"settings": settings})

    try:
        # Wait for both tasks even if one fails so the engine is disposed only after
        # every connection is idle (otherwise the slow task dies in aiosqlite's thread).
        results = await asyncio.gather(process(101, 0.0), process(102, 0.15), return_exceptions=True)
        for outcome in results:
            if isinstance(outcome, BaseException):
                raise outcome
        assert results == ["ok", "ok"]
        async with factory() as session:
            ids = (await session.execute(select(User.id).order_by(User.id))).scalars().all()
            assert ids == [101, 102]
    finally:
        await bot.session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_write_lock_is_released_before_network_io(tmp_path: Path) -> None:
    await _run_two_users(tmp_path, commit_hook=True)


@pytest.mark.asyncio
async def test_without_commit_hook_second_user_hits_database_is_locked(tmp_path: Path) -> None:
    """Documents the failure mode the hook prevents (same shape as the production alert)."""
    with pytest.raises(OperationalError, match="database is locked"):
        await _run_two_users(tmp_path, commit_hook=False)
