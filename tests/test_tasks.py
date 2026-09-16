import pytest

from app.db.models import LedgerKind, TaskKind, User
from app.db.seed import seed_catalog
from app.services import daily, events, ledger, referrals
from app.services import tasks as task_service
from app.services.antifraud import bump_activity
from app.services.errors import AlreadyClaimed, EconomyError, ValidationError


async def _user(session, user_id: int) -> User:
    user = User(id=user_id, first_name=f"T{user_id}")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_seed_and_listing(session) -> None:
    await seed_catalog(session)
    tasks = await task_service.list_tasks(session)
    assert {t.slug for t in tasks} >= {"invite_one", "streak_three", "first_boost"}
    assert await task_service.completed_task_ids(session, 1) == set()


@pytest.mark.asyncio
async def test_create_update_toggle_delete(session) -> None:
    task = await task_service.create_task(
        session, title="Подпишись на канал", description="", kind="subscribe", reward=7, target="@kodo"
    )
    assert task.slug.startswith("task_")
    assert task.payload == {"channel": "@kodo"}
    assert task_service.task_target(task) == "@kodo"

    dup = await task_service.create_task(
        session, title="Подпишись на канал", description="", kind="subscribe", reward=7, target="@kodo2"
    )
    assert dup.slug != task.slug

    await task_service.update_task(session, task.id, reward=9, title="Новое имя")
    assert task.reward == 9 and task.title == "Новое имя"
    with pytest.raises(ValidationError):
        await task_service.update_task(session, task.id, reward=0)
    with pytest.raises(ValidationError):
        await task_service.update_task(session, task.id, slug="x")

    await task_service.toggle_task(session, task.id)
    assert task.is_active is False
    assert await task_service.delete_task(session, task.id) is True
    assert await task_service.get_task(session, task.id) is None


@pytest.mark.asyncio
async def test_build_payload_validation() -> None:
    assert task_service.build_payload("invite", "3") == {"invites": 3}
    assert task_service.build_payload("streak", "5") == {"streak": 5}
    assert task_service.build_payload("custom", "https://x.y") == {"url": "https://x.y"}
    assert task_service.build_payload("custom", "") == {}
    for kind, target in (("invite", "0"), ("streak", "abc"), ("subscribe", ""), ("custom", "ftp://x")):
        with pytest.raises(ValidationError):
            task_service.build_payload(kind, target)
    with pytest.raises(ValidationError):
        task_service.build_payload("nope", "1")


@pytest.mark.asyncio
async def test_subscribe_task_uses_membership_checker(session, settings) -> None:
    user = await _user(session, 401)
    task = await task_service.create_task(
        session, title="Канал", description="", kind="subscribe", reward=10, target="@kodo"
    )
    seen: list[str] = []

    async def not_member(channel: str) -> bool | None:
        seen.append(channel)
        return False

    async def member(channel: str) -> bool | None:
        return True

    with pytest.raises(EconomyError, match="Подписка ещё не найдена"):
        await task_service.claim_task(
            session, user=user, task_id=task.id, settings=settings, membership_checker=not_member
        )
    assert seen == ["@kodo"]
    with pytest.raises(EconomyError, match="временно недоступна"):
        await task_service.claim_task(session, user=user, task_id=task.id, settings=settings)

    _, amount = await task_service.claim_task(
        session, user=user, task_id=task.id, settings=settings, membership_checker=member
    )
    assert amount == 10
    assert await ledger.get_balance(session, user.id) == 10
    with pytest.raises(AlreadyClaimed):
        await task_service.claim_task(
            session, user=user, task_id=task.id, settings=settings, membership_checker=member
        )


@pytest.mark.asyncio
async def test_invite_and_streak_requirements(session, settings) -> None:
    referrer = await _user(session, 402)
    invite = await task_service.create_task(
        session, title="Друг", description="", kind="invite", reward=15, target="1"
    )
    streak = await task_service.create_task(
        session, title="Серия", description="", kind="streak", reward=20, target="3"
    )
    with pytest.raises(EconomyError, match="Активных рефералов: 0 из 1"):
        await task_service.claim_task(session, user=referrer, task_id=invite.id, settings=settings)
    with pytest.raises(EconomyError, match="Нужна серия 3"):
        await task_service.claim_task(session, user=referrer, task_id=streak.id, settings=settings)

    referee = await _user(session, 403)
    await referrals.attach_referrer(session, user=referee, payload="ref_402", settings=settings)
    await bump_activity(session, referee, settings.min_referral_activity)
    await referrals.activate_if_ready(session, user=referee, settings=settings)
    _, amount = await task_service.claim_task(session, user=referrer, task_id=invite.id, settings=settings)
    assert amount == 15

    referrer.streak = 3
    _, amount = await task_service.claim_task(session, user=referrer, task_id=streak.id, settings=settings)
    assert amount == 20


@pytest.mark.asyncio
async def test_auto_completion_via_events(session, settings) -> None:
    await seed_catalog(session)
    referrer = await _user(session, 404)
    referee = await _user(session, 405)
    await referrals.attach_referrer(session, user=referee, payload="ref_404", settings=settings)
    referee.activity_score = settings.min_referral_activity - 1
    events.drain(session)

    # The referee's first daily claim activates them → referrer's "invite_one" auto-completes.
    await daily.claim_daily(session, user=referee, settings=settings)
    done = await task_service.completed_task_ids(session, referrer.id)
    invite_task = next(t for t in await task_service.list_tasks(session) if t.slug == "invite_one")
    assert invite_task.id in done
    names = [e.name for e in events.peek(session)]
    assert "referral_activated" in names
    assert "task_completed" in names
    entries = await ledger.history(session, referrer.id, limit=10)
    assert {e.kind for e in entries} >= {LedgerKind.REFERRAL_BONUS.value, LedgerKind.TASK.value}


@pytest.mark.asyncio
async def test_boost_event_task_cannot_be_claimed_manually(session, settings) -> None:
    await seed_catalog(session)
    user = await _user(session, 406)
    first_boost = next(t for t in await task_service.list_tasks(session) if t.slug == "first_boost")
    assert first_boost.kind == TaskKind.CUSTOM.value
    with pytest.raises(EconomyError, match="автоматически"):
        await task_service.claim_task(session, user=user, task_id=first_boost.id, settings=settings)


@pytest.mark.asyncio
async def test_delete_with_completions_deactivates(session, settings) -> None:
    user = await _user(session, 407)
    task = await task_service.create_task(
        session, title="Ссылка", description="", kind="custom", reward=3, target="https://example.com"
    )
    await task_service.claim_task(session, user=user, task_id=task.id, settings=settings)
    assert await task_service.completion_count(session, task.id) == 1
    assert await task_service.delete_task(session, task.id) is False
    assert task.is_active is False
