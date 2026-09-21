from collections.abc import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerKind, Task, TaskKind, User, UserTask
from app.services import events, ledger, referrals
from app.services.antifraud import bump_activity, ensure_action_cooldown, ensure_not_banned
from app.services.boosts import active_multiplier_bp, slugify
from app.services.channels import validate_channel_entry
from app.services.errors import AlreadyClaimed, EconomyError, NotFound, ValidationError
from app.services.levels import XP_TASK, add_xp, apply_multipliers, info_for_xp
from app.services.referrals import activated_invite_count

# Returns True (member), False (not a member) or None (cannot check → fail-open).
MembershipChecker = Callable[[str], Awaitable[bool | None]]


async def list_tasks(session: AsyncSession) -> list[Task]:
    result = await session.execute(
        select(Task).where(Task.is_active.is_(True)).order_by(Task.sort_order, Task.id)
    )
    return list(result.scalars().all())


async def list_all_tasks(session: AsyncSession) -> list[Task]:
    result = await session.execute(select(Task).order_by(Task.sort_order, Task.id))
    return list(result.scalars().all())


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    return await session.get(Task, task_id)


async def completed_task_ids(session: AsyncSession, user_id: int) -> set[int]:
    result = await session.execute(select(UserTask.task_id).where(UserTask.user_id == user_id))
    return set(result.scalars().all())


async def completion_count(session: AsyncSession, task_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(UserTask).where(UserTask.task_id == task_id)
    )
    return int(result.scalar_one())


def task_target(task: Task) -> str:
    """Human-readable requirement (channel, invites, streak, url)."""
    payload = task.payload or {}
    if task.kind == TaskKind.SUBSCRIBE.value:
        return str(payload.get("channel", ""))
    if task.kind == TaskKind.INVITE.value:
        return f"{payload.get('invites', 1)} реф."
    if task.kind == TaskKind.STREAK.value:
        return f"{payload.get('streak', 3)} дн."
    return str(payload.get("url", ""))


async def _complete(
    session: AsyncSession,
    *,
    user: User,
    task: Task,
    settings: Settings,
    check_cooldown: bool = True,
) -> tuple[UserTask, int]:
    """Credit the task. Returns the completion row and the amount actually paid."""
    existing = await session.execute(
        select(UserTask).where(UserTask.user_id == user.id, UserTask.task_id == task.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise AlreadyClaimed("Задание уже выполнено")

    ensure_not_banned(user)
    if check_cooldown:
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
        reference=f"task:{task.slug}"[:64],
        extra={"task_id": task.id, "base": task.reward},
    )
    await add_xp(session, user, XP_TASK)
    await bump_activity(session, user, 1)
    await referrals.activate_if_ready(session, user=user, settings=settings, boost_bp=boost_bp)
    await referrals.share_earning(
        session,
        earner=user,
        base_amount=amount,
        settings=settings,
        source=f"task:{task.slug}",
        boost_bp=boost_bp,
    )
    await session.flush()
    return row, amount


async def try_complete_event(
    session: AsyncSession,
    *,
    user: User,
    event: str,
    settings: Settings,
) -> list[UserTask]:
    """Auto-complete tasks triggered by an event (no cooldown, user notified via events)."""
    completed = await completed_task_ids(session, user.id)
    tasks = await list_tasks(session)
    done: list[UserTask] = []
    for task in tasks:
        if task.id in completed:
            continue
        payload = task.payload or {}
        ok = False
        if event == "daily_claimed" and task.kind == TaskKind.STREAK.value:
            ok = user.streak >= int(payload.get("streak", 3))
        elif event == "boost_purchased" and payload.get("event") == "boost_purchased":
            ok = True
        elif event == "invite_activated" and task.kind == TaskKind.INVITE.value:
            invites = await activated_invite_count(session, user.id)
            ok = invites >= int(payload.get("invites", 1))
        if not ok:
            continue
        row, amount = await _complete(session, user=user, task=task, settings=settings, check_cooldown=False)
        done.append(row)
        events.emit(
            session,
            "task_completed",
            user_id=user.id,
            title=task.title,
            amount=amount,
        )
    return done


async def claim_task(
    session: AsyncSession,
    *,
    user: User,
    task_id: int,
    settings: Settings,
    membership_checker: MembershipChecker | None = None,
) -> tuple[UserTask, int]:
    task = await session.get(Task, task_id)
    if task is None or not task.is_active:
        raise EconomyError("Задание не найдено")

    payload = task.payload or {}
    if task.kind == TaskKind.INVITE.value:
        needed = int(payload.get("invites", 1))
        have = await activated_invite_count(session, user.id)
        if have < needed:
            raise EconomyError(f"Активных рефералов: {have} из {needed}. Пригласите ещё.")
    elif task.kind == TaskKind.STREAK.value:
        needed = int(payload.get("streak", 3))
        if user.streak < needed:
            raise EconomyError(f"Нужна серия {needed} дн. Сейчас: {user.streak}.")
    elif task.kind == TaskKind.SUBSCRIBE.value:
        channel = str(payload.get("channel", "")).strip()
        if channel:
            if membership_checker is None:
                raise EconomyError("Проверка подписки временно недоступна")
            verdict = await membership_checker(channel)
            if verdict is False:
                raise EconomyError("Подписка ещё не найдена. Подпишитесь и нажмите «Проверить».")
    elif payload.get("event") == "boost_purchased":
        raise EconomyError("Купите буст — задание засчитается автоматически")

    return await _complete(session, user=user, task=task, settings=settings)


# --- admin CRUD -----------------------------------------------------------------------


def build_payload(kind: str, target: str) -> dict:
    target = target.strip()
    if kind == TaskKind.SUBSCRIBE.value:
        if not target:
            raise ValidationError("Укажите канал: @username или -100…|ссылка|название")
        problem = validate_channel_entry(target)
        if problem:
            raise ValidationError(f"Канал: {problem}")
        return {"channel": target}
    if kind == TaskKind.INVITE.value:
        if not target.isdigit() or int(target) < 1:
            raise ValidationError("Укажите число рефералов ≥ 1")
        return {"invites": int(target)}
    if kind == TaskKind.STREAK.value:
        if not target.isdigit() or int(target) < 1:
            raise ValidationError("Укажите длину серии ≥ 1")
        return {"streak": int(target)}
    if kind == TaskKind.CUSTOM.value:
        if target and not target.startswith(("http://", "https://", "tg://")):
            raise ValidationError("Ссылка должна начинаться с https://")
        return {"url": target} if target else {}
    raise ValidationError("Неизвестный тип задания")


async def create_task(
    session: AsyncSession,
    *,
    title: str,
    description: str,
    kind: str,
    reward: int,
    target: str,
    sort_order: int = 100,
) -> Task:
    if kind not in {item.value for item in TaskKind}:
        raise ValidationError("Неизвестный тип задания")
    if reward < 1:
        raise ValidationError("Награда должна быть ≥ 1 ⭐")
    payload = build_payload(kind, target)
    slug = await _unique_slug(session, slugify(title, prefix="task_"))
    task = Task(
        slug=slug,
        title=title.strip()[:128],
        description=description.strip(),
        kind=kind,
        reward=reward,
        payload=payload,
        is_active=True,
        sort_order=sort_order,
    )
    session.add(task)
    await session.flush()
    return task


async def update_task(session: AsyncSession, task_id: int, **fields) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise NotFound("Задание не найдено")
    allowed = {"title", "description", "reward", "sort_order", "payload"}
    for key, value in fields.items():
        if key not in allowed:
            raise ValidationError(f"Поле {key} нельзя изменить")
        if key == "reward" and int(value) < 1:
            raise ValidationError("Награда должна быть ≥ 1 ⭐")
        setattr(task, key, value)
    await session.flush()
    return task


async def toggle_task(session: AsyncSession, task_id: int) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise NotFound("Задание не найдено")
    task.is_active = not task.is_active
    await session.flush()
    return task


async def delete_task(session: AsyncSession, task_id: int) -> bool:
    """Hard-delete when nobody completed it, otherwise deactivate. True when deleted."""
    task = await session.get(Task, task_id)
    if task is None:
        raise NotFound("Задание не найдено")
    if await completion_count(session, task_id) > 0:
        task.is_active = False
        await session.flush()
        return False
    await session.delete(task)
    await session.flush()
    return True


async def _unique_slug(session: AsyncSession, slug: str) -> str:
    candidate = slug
    counter = 2
    while True:
        exists = await session.execute(select(Task.id).where(Task.slug == candidate))
        if exists.scalar_one_or_none() is None:
            return candidate
        candidate = f"{slug}_{counter}"[:64]
        counter += 1
