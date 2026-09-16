import secrets
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import PAGE_SIZE, parse_id, safe_answer, safe_edit
from app.services import audit
from app.services import promo as promo_service
from app.services.errors import EconomyError

router = Router(name="admin.promo")


async def _list_view(session: AsyncSession, page: int):
    total = await promo_service.count_promos(session)
    items = await promo_service.list_promos(session, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    return texts.promo_home(items, page, total, PAGE_SIZE), kb.promo_home(items, page, total)


@router.callback_query(F.data.regexp(r"^admin:promo:list:(\d+)$"))
async def promo_list(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _list_view(session, parse_id(call.data))
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "admin:promo:new")
async def promo_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.promo_code)
    await state.set_data({})
    await safe_answer(call)
    await safe_edit(call.message, texts.promo_new_code(), kb.cancel_to("admin:promo:list:0"))


@router.message(StateFilter(AdminFSM.promo_code), F.text)
async def promo_new_code(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    code = secrets.token_hex(4).upper() if raw.lower() == "auto" else promo_service.normalize_code(raw)
    await state.update_data(code=code)
    await state.set_state(AdminFSM.promo_reward)
    await message.answer(texts.promo_new_reward(), reply_markup=kb.cancel_to("admin:promo:list:0"))


@router.message(StateFilter(AdminFSM.promo_reward), F.text)
async def promo_new_reward(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("Нужно целое число ≥ 1.")
        return
    await state.update_data(reward=int(raw))
    await state.set_state(AdminFSM.promo_limit)
    await message.answer(texts.promo_new_limit(), reply_markup=kb.cancel_to("admin:promo:list:0"))


@router.message(StateFilter(AdminFSM.promo_limit), F.text)
async def promo_new_limit(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно целое число (0 — без лимита).")
        return
    await state.update_data(max_uses=int(raw))
    await state.set_state(AdminFSM.promo_days)
    await message.answer(texts.promo_new_days(), reply_markup=kb.cancel_to("admin:promo:list:0"))


@router.message(StateFilter(AdminFSM.promo_days), F.text)
async def promo_new_days(message: Message, session: AsyncSession, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно целое число (0 — бессрочно).")
        return
    data = await state.get_data()
    expires_at = datetime.now(UTC) + timedelta(days=int(raw)) if int(raw) > 0 else None
    try:
        promo = await promo_service.create_promo(
            session,
            code=data["code"],
            reward=int(data["reward"]),
            max_uses=int(data.get("max_uses", 0)),
            expires_at=expires_at,
            created_by=message.from_user.id,
        )
    except EconomyError as exc:
        await message.answer(exc.message)
        await state.set_state(AdminFSM.promo_code)
        await message.answer(texts.promo_new_code(), reply_markup=kb.cancel_to("admin:promo:list:0"))
        return
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="promo.create",
        target_type="promo",
        target_id=promo.id,
        code=promo.code,
        reward=promo.reward,
    )
    await state.clear()
    await message.answer(texts.promo_card(promo), reply_markup=kb.promo_card(promo))


@router.callback_query(F.data.regexp(r"^admin:promo:(\d+)$"))
async def promo_card(call: CallbackQuery, session: AsyncSession) -> None:
    try:
        promo = await promo_service.get_promo(session, parse_id(call.data))
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call)
    await safe_edit(call.message, texts.promo_card(promo), kb.promo_card(promo))


@router.callback_query(F.data.regexp(r"^admin:promo:(\d+):tg$"))
async def promo_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    try:
        promo = await promo_service.toggle_promo(session, parse_id(call.data, -2))
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="promo.toggle",
        target_type="promo",
        target_id=promo.id,
        active=promo.is_active,
    )
    await safe_answer(call, "Включён" if promo.is_active else "Выключен")
    await safe_edit(call.message, texts.promo_card(promo), kb.promo_card(promo))


@router.callback_query(F.data.regexp(r"^admin:promo:(\d+):del$"))
async def promo_delete(call: CallbackQuery, session: AsyncSession) -> None:
    promo_id = parse_id(call.data, -2)
    try:
        deleted = await promo_service.delete_promo(session, promo_id)
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="promo.delete",
        target_type="promo",
        target_id=promo_id,
        hard=deleted,
    )
    await safe_answer(call, "Удалён" if deleted else "Были активации — промокод выключен", alert=not deleted)
    text, markup = await _list_view(session, 0)
    await safe_edit(call.message, text, markup)
