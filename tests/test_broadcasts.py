import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import CopyMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Base, Broadcast, BroadcastStatus, User
from app.db.session import create_engine
from app.services import broadcasts
from app.services.errors import ValidationError


@pytest.fixture
async def factory(settings):
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


async def _seed_users(factory, count: int) -> None:
    async with factory() as session:
        for i in range(1, count + 1):
            user = User(id=i, first_name=f"U{i}", last_action_at=datetime.now(UTC))
            if i == 3:
                user.is_banned = True
            if i == 4:
                user.blocked_bot_at = datetime.now(UTC)
            if i == 5:
                user.last_action_at = datetime.now(UTC) - timedelta(days=30)
            if i == 6:
                user.referral_activated = True
            session.add(user)
        await session.commit()


@pytest.mark.asyncio
async def test_create_broadcast_counts_audience(factory) -> None:
    await _seed_users(factory, 6)
    async with factory() as session:
        row = await broadcasts.create_broadcast(
            session, admin_id=1, from_chat_id=1, message_id=10, audience="all"
        )
        assert row.total == 4  # 6 users minus banned(3) minus blocked(4)
        active = await broadcasts.audience_size(session, "active_7d")
        assert active == 3  # user 5 inactive
        assert await broadcasts.audience_size(session, "activated") == 1
        with pytest.raises(ValidationError):
            await broadcasts.create_broadcast(
                session, admin_id=1, from_chat_id=1, message_id=10, audience="everyone"
            )
        with pytest.raises(ValidationError):
            await broadcasts.create_broadcast(
                session, admin_id=1, from_chat_id=1, message_id=10, audience="all", button_text="x"
            )
        with pytest.raises(ValidationError):
            await broadcasts.create_broadcast(
                session,
                admin_id=1,
                from_chat_id=1,
                message_id=10,
                audience="all",
                button_text="x",
                button_url="javascript:alert(1)",
            )


@pytest.mark.asyncio
async def test_runner_sends_marks_blocked_and_handles_retry(factory) -> None:
    await _seed_users(factory, 6)
    sent: list[int] = []
    retried = {"count": 0}

    async def sender(chat_id: int, broadcast: Broadcast) -> None:
        if chat_id == 2:
            raise TelegramForbiddenError(
                method=CopyMessage(chat_id=2, from_chat_id=1, message_id=1),
                message="bot was blocked by the user",
            )
        if chat_id == 6 and retried["count"] == 0:
            retried["count"] += 1
            raise TelegramRetryAfter(
                method=CopyMessage(chat_id=6, from_chat_id=1, message_id=1), message="flood", retry_after=0
            )
        sent.append(chat_id)

    progress: list[tuple[int, int, int]] = []

    async def on_progress(row: Broadcast, chat_id: int, message_id: int) -> None:
        progress.append((row.sent, chat_id, message_id))

    async with factory() as session:
        row = await broadcasts.create_broadcast(
            session, admin_id=1, from_chat_id=1, message_id=10, audience="all"
        )
        await session.commit()
        broadcast_id = row.id

    runner = broadcasts.BroadcastRunner(
        factory, sender=sender, rate_per_sec=1000, progress_every=2, progress_callback=on_progress
    )
    runner.watch(broadcast_id, 777, 888)
    await runner.start(broadcast_id)

    assert sorted(sent) == [1, 5, 6]
    assert retried["count"] == 1
    async with factory() as session:
        row = await session.get(Broadcast, broadcast_id)
        assert row.status == BroadcastStatus.DONE.value
        assert (row.sent, row.blocked, row.failed) == (3, 1, 0)
        assert row.finished_at is not None
        blocked_user = await session.get(User, 2)
        assert blocked_user.blocked_bot_at is not None
    assert progress and progress[-1][1:] == (777, 888)
    assert not runner.is_running(broadcast_id)


@pytest.mark.asyncio
async def test_runner_cancel(factory) -> None:
    await _seed_users(factory, 6)
    started = asyncio.Event()

    async def slow_sender(chat_id: int, broadcast: Broadcast) -> None:
        started.set()
        await asyncio.sleep(0.05)

    async with factory() as session:
        row = await broadcasts.create_broadcast(
            session, admin_id=1, from_chat_id=1, message_id=10, audience="all"
        )
        await session.commit()
        broadcast_id = row.id

    runner = broadcasts.BroadcastRunner(factory, sender=slow_sender, rate_per_sec=1000)
    task = runner.start(broadcast_id)
    await started.wait()
    assert runner.cancel(broadcast_id) is True
    await task
    async with factory() as session:
        row = await session.get(Broadcast, broadcast_id)
        assert row.status == BroadcastStatus.CANCELLED.value
        assert row.sent < row.total
    assert runner.cancel(broadcast_id) is False


@pytest.mark.asyncio
async def test_runner_shutdown_stops_tasks(factory) -> None:
    await _seed_users(factory, 6)

    async def slow_sender(chat_id: int, broadcast: Broadcast) -> None:
        await asyncio.sleep(0.05)

    async with factory() as session:
        row = await broadcasts.create_broadcast(
            session, admin_id=1, from_chat_id=1, message_id=10, audience="all"
        )
        await session.commit()
        broadcast_id = row.id
    runner = broadcasts.BroadcastRunner(factory, sender=slow_sender, rate_per_sec=1000)
    runner.start(broadcast_id)
    await asyncio.sleep(0.01)
    await runner.shutdown()
    async with factory() as session:
        row = await session.get(Broadcast, broadcast_id)
        assert row.status in {BroadcastStatus.CANCELLED.value, BroadcastStatus.DONE.value}
        assert await broadcasts.running_broadcast(session) is None
