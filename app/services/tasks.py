from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerKind, Task, User, UserTask
from app.services import ledger, referrals
from app.services.referrals import activated_invite_count
from app.services.antifraud import bump_activity, ensure_action_cooldown, ensure_not_banned
from app.services.boosts import active_multiplier_bp
from app.services.errors import AlreadyClaimed, EconomyError
from app.services.levels import add_xp, apply_multipliers, info_for_xp


async def list_tasks(session: AsyncSession) -> list[Task]:
    result = await session.execute(
        select(Task).where(Task.is_active.is_(True)).order_by(Task.sort_order, Task.id)
    )
    return list(result.scalars().all())


async def completed_task_ids(session: AsyncSession, user_id: int) -> set[int]:
    result = await session.execute(select(UserTask.task_id).where(UserTask.user_id == user_id))
    return set(result.scalars().all())


async def _complete(
    session: AsyncSession,
    *,
    user: User,
    task: Task,
    settings: Settings,
) -> UserTask:
    existing = await session.execute(
        select(UserTask).where(UserTask.user_id == user.id, UserTask.task_id == task.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise AlreadyClaimed("Задание уже выполнено")

    ensure_not_banned(user)
    ensure_action_cooldown(user, settings)
    level_bp = info_for_xp(user.xp).multiplier_bp
    boost_bp = await active_multiplier_bp(session, user.id)
    amount = apply_multipliers(task.reward, level_bp, boost_bp)
    row = UserTask(user_id=user.id, task_id=task.id)
    session.add(row)
    await ledger.credit(
        session,
        user_id=user.id,
        amount=amount,
        kind=LedgerKind.TASK,
        reference=f"task:{task.slug}",
        extra={"task_id": task.id, "base": task.reward},
    )
    await add_xp(session, user, 12)
    await bump_activity(session, user, 1)
    await referrals.activate_if_ready(
        session, user=user, settings=settings, boost_bp=boost_bp
    )
    await referrals.share_earning(
        session,
        earner=user,
        base_amount=amount,
        settings=settings,
        source=f"task:{task.slug}",
        boost_bp=boost_bp,
    )
    await session.flush()
    return row


async def try_complete_event(
    session: AsyncSession,
    *,
    user: User,
    event: str,
    settings: Settings,
) -> list[UserTask]:
    completed = await completed_task_ids(session, user.id)
    tasks = await list_tasks(session)
    done: list[UserTask] = []
    for task in tasks:
        if task.id in completed:
            continue
        payload = task.payload or {}
        ok = False
        if event == "daily_claimed" and task.kind == "streak":
            ok = user.streak >= int(payload.get("streak", 3))
        elif event == "boost_purchased" and payload.get("event") == "boost_purchased":
            ok = True
        elif event == "invite_activated" and task.kind == "invite":
            invites = await activated_invite_count(session, user.id)
            ok = invites >= int(payload.get("invites", 1))
        if ok:
            done.append(await _complete(session, user=user, task=task, settings=settings))
    return done


async def claim_task(
    session: AsyncSession,
    *,
    user: User,
    task_id: int,
    settings: Settings,
    subscribed_channels: Sequence[str] | None = None,
) -> UserTask:
    task = await session.get(Task, task_id)
    if task is None or not task.is_active:
        raise EconomyError("Задание не найдено")

    payload = task.payload or {}
    if task.kind == "invite":
        needed = int(payload.get("invites", 1))
        if await activated_invite_count(session, user.id) < needed:
            raise EconomyError("Сначала активируйте нужное число рефералов")
    elif task.kind == "streak":
        needed = int(payload.get("streak", 3))
        if user.streak < needed:
            raise EconomyError(f"Нужна серия {needed} дней")
    elif task.kind == "subscribe":
        channel = str(payload.get("channel", "")).lower()
        have = {item.lower() for item in (subscribed_channels or [])}
        if channel and channel not in have:
            raise EconomyError("Подписка ещё не подтверждена")
    elif payload.get("event") == "boost_purchased":
        raise EconomyError("Купите буст — задание засчитается автоматически")

    return await _complete(session, user=user, task=task, settings=settings)
