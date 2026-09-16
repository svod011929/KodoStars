"""Tasks and boosts management (create wizards + inline editing)."""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import parse_id, safe_answer, safe_edit
from app.db.models import BoostKind, BoostProduct, Task, TaskKind, UserBoost, UserTask
from app.services import audit, boosts
from app.services import tasks as task_service
from app.services.errors import EconomyError

router = Router(name="admin.catalog")

TASK_FIELD_LABELS = {
    "title": "название",
    "desc": "описание",
    "reward": "награда (⭐)",
    "target": "условие",
    "order": "порядок сортировки",
}
BOOST_FIELD_LABELS = {
    "title": "название",
    "desc": "описание",
    "price": "цена XTR",
    "amount": "количество Stars",
    "mult": "множитель и часы (например 2 24)",
}


# --- tasks --------------------------------------------------------------------------


async def _completions(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(select(UserTask.task_id, func.count()).group_by(UserTask.task_id))
    return {int(task_id): int(count) for task_id, count in rows.all()}


async def _tasks_view(session: AsyncSession):
    items = await task_service.list_all_tasks(session)
    return texts.tasks_home(items, await _completions(session)), kb.tasks_home(items)


async def _task_card(session: AsyncSession, task: Task):
    return texts.task_card(task, await task_service.completion_count(session, task.id)), kb.task_card(task)


@router.callback_query(F.data == "admin:tasks")
async def tasks_home(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _tasks_view(session)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "admin:task:new")
async def task_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(call)
    await safe_edit(call.message, texts.task_new_kind(), kb.task_kinds())


@router.callback_query(F.data.regexp(r"^admin:task:new:(\w+)$"))
async def task_new_kind(call: CallbackQuery, state: FSMContext) -> None:
    kind = (call.data or "").split(":")[-1]
    if kind not in {item.value for item in TaskKind}:
        await safe_answer(call, "Неизвестный тип", alert=True)
        return
    await state.set_state(AdminFSM.task_title)
    await state.set_data({"kind": kind})
    await safe_answer(call)
    await safe_edit(call.message, texts.task_new_title(), kb.cancel_to("admin:tasks"))


@router.message(StateFilter(AdminFSM.task_title), F.text)
async def task_new_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip()[:128])
    await state.set_state(AdminFSM.task_desc)
    await message.answer(texts.task_new_desc(), reply_markup=kb.cancel_to("admin:tasks"))


@router.message(StateFilter(AdminFSM.task_desc), F.text)
async def task_new_desc(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    await state.update_data(description="" if raw == "-" else raw[:1000])
    await state.set_state(AdminFSM.task_reward)
    await message.answer(texts.task_new_reward(), reply_markup=kb.cancel_to("admin:tasks"))


@router.message(StateFilter(AdminFSM.task_reward), F.text)
async def task_new_reward(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("Нужно целое число ≥ 1.")
        return
    await state.update_data(reward=int(raw))
    data = await state.get_data()
    await state.set_state(AdminFSM.task_target)
    await message.answer(texts.task_new_target(data["kind"]), reply_markup=kb.cancel_to("admin:tasks"))


@router.message(StateFilter(AdminFSM.task_target), F.text)
async def task_new_target(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    raw = (message.text or "").strip()
    target = "" if raw == "-" else raw
    try:
        task = await task_service.create_task(
            session,
            title=data["title"],
            description=data.get("description", ""),
            kind=data["kind"],
            reward=int(data["reward"]),
            target=target,
        )
    except EconomyError as exc:
        await message.answer(exc.message)
        return
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="task.create",
        target_type="task",
        target_id=task.id,
        title=task.title,
    )
    await state.clear()
    text, markup = await _task_card(session, task)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^admin:task:(\d+)$"))
async def task_card(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    task = await session.get(Task, parse_id(call.data))
    if task is None:
        await safe_answer(call, "Задание не найдено", alert=True)
        return
    text, markup = await _task_card(session, task)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:task:(\d+):tg$"))
async def task_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    try:
        task = await task_service.toggle_task(session, parse_id(call.data, -2))
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="task.toggle",
        target_type="task",
        target_id=task.id,
        active=task.is_active,
    )
    text, markup = await _task_card(session, task)
    await safe_answer(call, "Включено" if task.is_active else "Выключено")
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:task:(\d+):del$"))
async def task_delete(call: CallbackQuery, session: AsyncSession) -> None:
    task_id = parse_id(call.data, -2)
    try:
        deleted = await task_service.delete_task(session, task_id)
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="task.delete",
        target_type="task",
        target_id=task_id,
        hard=deleted,
    )
    await safe_answer(
        call, "Удалено" if deleted else "Есть выполнения — задание выключено", alert=not deleted
    )
    text, markup = await _tasks_view(session)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:task:(\d+):e:(\w+)$"))
async def task_edit_start(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    parts = (call.data or "").split(":")
    task_id, field = int(parts[2]), parts[4]
    task = await session.get(Task, task_id)
    if task is None or field not in TASK_FIELD_LABELS:
        await safe_answer(call, "Не найдено", alert=True)
        return
    current = {
        "title": task.title,
        "desc": task.description,
        "reward": task.reward,
        "target": task_service.task_target(task),
        "order": task.sort_order,
    }[field]
    await state.set_state(AdminFSM.task_edit)
    await state.set_data({"task_id": task_id, "field": field})
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.edit_prompt(TASK_FIELD_LABELS[field], current),
        kb.cancel_to(f"admin:task:{task_id}"),
    )


@router.message(StateFilter(AdminFSM.task_edit), F.text)
async def task_edit_apply(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    task = await session.get(Task, int(data.get("task_id", 0)))
    field = data.get("field")
    raw = (message.text or "").strip()
    if task is None:
        await state.clear()
        await message.answer("Задание не найдено.")
        return
    try:
        if field == "title":
            await task_service.update_task(session, task.id, title=raw[:128])
        elif field == "desc":
            await task_service.update_task(session, task.id, description="" if raw == "-" else raw[:1000])
        elif field == "reward":
            if not raw.isdigit():
                raise EconomyError("Нужно целое число")
            await task_service.update_task(session, task.id, reward=int(raw))
        elif field == "order":
            if not raw.lstrip("-").isdigit():
                raise EconomyError("Нужно целое число")
            await task_service.update_task(session, task.id, sort_order=int(raw))
        elif field == "target":
            payload = task_service.build_payload(task.kind, "" if raw == "-" else raw)
            if task.kind == TaskKind.CUSTOM.value and (task.payload or {}).get("event"):
                payload["event"] = task.payload["event"]
            await task_service.update_task(session, task.id, payload=payload)
    except EconomyError as exc:
        await message.answer(exc.message)
        return
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="task.update",
        target_type="task",
        target_id=task.id,
        field=field,
    )
    await state.clear()
    text, markup = await _task_card(session, task)
    await message.answer(text, reply_markup=markup)


# --- boosts -------------------------------------------------------------------------


async def _sales(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(select(UserBoost.product_id, func.count()).group_by(UserBoost.product_id))
    return {int(pid): int(count) for pid, count in rows.all()}


async def _boosts_view(session: AsyncSession):
    items = await boosts.list_all_products(session)
    return texts.boosts_home(items, await _sales(session)), kb.boosts_home(items)


async def _boost_card(session: AsyncSession, product: BoostProduct):
    sales = (await _sales(session)).get(product.id, 0)
    return texts.boost_card(product, sales), kb.boost_card(product)


@router.callback_query(F.data == "admin:boosts")
async def boosts_home(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _boosts_view(session)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "admin:boost:new")
async def boost_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(call)
    await safe_edit(call.message, texts.boost_new_kind(), kb.boost_kinds())


@router.callback_query(F.data.regexp(r"^admin:boost:new:(\w+)$"))
async def boost_new_kind(call: CallbackQuery, state: FSMContext) -> None:
    kind = (call.data or "").split(":")[-1]
    if kind not in {item.value for item in BoostKind}:
        await safe_answer(call, "Неизвестный тип", alert=True)
        return
    await state.set_state(AdminFSM.boost_title)
    await state.set_data({"kind": kind})
    await safe_answer(call)
    await safe_edit(call.message, texts.boost_new_title(), kb.cancel_to("admin:boosts"))


@router.message(StateFilter(AdminFSM.boost_title), F.text)
async def boost_new_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip()[:128])
    await state.set_state(AdminFSM.boost_desc)
    await message.answer(texts.boost_new_desc(), reply_markup=kb.cancel_to("admin:boosts"))


@router.message(StateFilter(AdminFSM.boost_desc), F.text)
async def boost_new_desc(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    await state.update_data(description="" if raw == "-" else raw[:1000])
    await state.set_state(AdminFSM.boost_price)
    await message.answer(texts.boost_new_price(), reply_markup=kb.cancel_to("admin:boosts"))


@router.message(StateFilter(AdminFSM.boost_price), F.text)
async def boost_new_price(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("Нужно целое число ≥ 1.")
        return
    await state.update_data(price=int(raw))
    data = await state.get_data()
    await state.set_state(AdminFSM.boost_param)
    await message.answer(texts.boost_new_param(data["kind"]), reply_markup=kb.cancel_to("admin:boosts"))


def _parse_multiplier(raw: str) -> tuple[int, int]:
    parts = raw.replace("×", "").replace("x", "").split()
    if len(parts) != 2:
        raise EconomyError("Формат: <code>2 24</code> — множитель и часы")
    try:
        multiplier = float(parts[0].replace(",", "."))
        hours = int(parts[1])
    except ValueError as exc:
        raise EconomyError("Формат: <code>2 24</code> — множитель и часы") from exc
    return round(multiplier * 100), hours


@router.message(StateFilter(AdminFSM.boost_param), F.text)
async def boost_new_param(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    raw = (message.text or "").strip()
    try:
        if data["kind"] == BoostKind.STARS_PACK.value:
            if not raw.isdigit():
                raise EconomyError("Нужно целое число")
            product = await boosts.create_product(
                session,
                title=data["title"],
                description=data.get("description", ""),
                xtr_price=int(data["price"]),
                kind=data["kind"],
                stars_amount=int(raw),
            )
        else:
            multiplier_bp, hours = _parse_multiplier(raw)
            product = await boosts.create_product(
                session,
                title=data["title"],
                description=data.get("description", ""),
                xtr_price=int(data["price"]),
                kind=data["kind"],
                multiplier_bp=multiplier_bp,
                duration_hours=hours,
            )
    except EconomyError as exc:
        await message.answer(exc.message)
        return
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="boost.create",
        target_type="boost",
        target_id=product.id,
        title=product.title,
    )
    await state.clear()
    text, markup = await _boost_card(session, product)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^admin:boost:(\d+)$"))
async def boost_card(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    product = await session.get(BoostProduct, parse_id(call.data))
    if product is None:
        await safe_answer(call, "Буст не найден", alert=True)
        return
    text, markup = await _boost_card(session, product)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:boost:(\d+):tg$"))
async def boost_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    try:
        product = await boosts.toggle_product(session, parse_id(call.data, -2))
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="boost.toggle",
        target_type="boost",
        target_id=product.id,
        active=product.is_active,
    )
    text, markup = await _boost_card(session, product)
    await safe_answer(call, "Включён" if product.is_active else "Выключен")
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:boost:(\d+):del$"))
async def boost_delete(call: CallbackQuery, session: AsyncSession) -> None:
    product_id = parse_id(call.data, -2)
    try:
        deleted = await boosts.delete_product(session, product_id)
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="boost.delete",
        target_type="boost",
        target_id=product_id,
        hard=deleted,
    )
    await safe_answer(call, "Удалён" if deleted else "Были продажи — буст выключен", alert=not deleted)
    text, markup = await _boosts_view(session)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:boost:(\d+):e:(\w+)$"))
async def boost_edit_start(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    parts = (call.data or "").split(":")
    product_id, field = int(parts[2]), parts[4]
    product = await session.get(BoostProduct, product_id)
    if product is None or field not in BOOST_FIELD_LABELS:
        await safe_answer(call, "Не найдено", alert=True)
        return
    current = {
        "title": product.title,
        "desc": product.description,
        "price": product.xtr_price,
        "amount": product.stars_amount,
        "mult": f"{product.multiplier_bp / 100:g} {product.duration_hours}",
    }[field]
    await state.set_state(AdminFSM.boost_edit)
    await state.set_data({"product_id": product_id, "field": field})
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.edit_prompt(BOOST_FIELD_LABELS[field], current),
        kb.cancel_to(f"admin:boost:{product_id}"),
    )


@router.message(StateFilter(AdminFSM.boost_edit), F.text)
async def boost_edit_apply(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    product = await session.get(BoostProduct, int(data.get("product_id", 0)))
    field = data.get("field")
    raw = (message.text or "").strip()
    if product is None:
        await state.clear()
        await message.answer("Буст не найден.")
        return
    try:
        if field == "title":
            await boosts.update_product(session, product.id, title=raw[:128])
        elif field == "desc":
            await boosts.update_product(session, product.id, description="" if raw == "-" else raw[:1000])
        elif field == "price":
            if not raw.isdigit():
                raise EconomyError("Нужно целое число")
            await boosts.update_product(session, product.id, xtr_price=int(raw))
        elif field == "amount":
            if not raw.isdigit() or int(raw) < 1:
                raise EconomyError("Нужно целое число ≥ 1")
            await boosts.update_product(session, product.id, stars_amount=int(raw))
        elif field == "mult":
            multiplier_bp, hours = _parse_multiplier(raw)
            if multiplier_bp <= 100 or hours < 1:
                raise EconomyError("Множитель > 1.00 и часы ≥ 1")
            await boosts.update_product(
                session, product.id, multiplier_bp=multiplier_bp, duration_hours=hours
            )
    except EconomyError as exc:
        await message.answer(exc.message)
        return
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="boost.update",
        target_type="boost",
        target_id=product.id,
        field=field,
    )
    await state.clear()
    text, markup = await _boost_card(session, product)
    await message.answer(text, reply_markup=markup)
