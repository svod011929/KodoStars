"""Admin ambassador queue: approve with custom terms, auto-post gate."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import parse_id, safe_answer, safe_edit
from app.db.models import AmbassadorStatus, User
from app.services import ambassadors as amb_service
from app.services import audit
from app.services.errors import EconomyError

router = Router(name="admin.ambassadors")


async def _hub(session: AsyncSession):
    pending = await amb_service.count_pending(session)
    approved = len(await amb_service.list_by_status(session, AmbassadorStatus.APPROVED.value, limit=500))
    return texts.ambassadors_hub(pending, approved), kb.ambassadors_hub(pending, approved)


async def _card(session: AsyncSession, slot_id: int):
    slot = await amb_service.get_slot(session, slot_id)
    owner = await session.get(User, slot.user_id)
    name = owner.display_name if owner else ""
    return texts.ambassador_card(slot, name), kb.ambassador_card(slot)


@router.callback_query(F.data == "admin:amb")
async def amb_home(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _hub(session)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "admin:amb:pending")
async def amb_pending(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    slots = await amb_service.list_by_status(session, AmbassadorStatus.PENDING.value)
    await safe_answer(call)
    if not slots:
        await safe_edit(call.message, texts.ambassadors_empty("очередь"), kb.ambassadors_hub(0, 0))
        return
    await safe_edit(call.message, "Очередь заявок:", kb.ambassadors_list(slots))


@router.callback_query(F.data == "admin:amb:list")
async def amb_list(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    slots = await amb_service.list_by_status(session, AmbassadorStatus.APPROVED.value)
    await safe_answer(call)
    if not slots:
        text, markup = await _hub(session)
        await safe_edit(call.message, texts.ambassadors_empty("одобренные"), markup)
        return
    await safe_edit(call.message, "Одобренные слоты:", kb.ambassadors_list(slots))


@router.callback_query(F.data.regexp(r"^admin:amb:(\d+)$"))
async def amb_view(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _card(session, parse_id(call.data))
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


async def _start_terms_fsm(call: CallbackQuery, state: FSMContext, slot_id: int, *, editing: bool) -> None:
    await state.set_data({"slot_id": slot_id, "editing": editing})
    await state.set_state(AdminFSM.amb_l1_bonus)
    await safe_answer(call)
    await safe_edit(call.message, texts.amb_ask_l1_bonus(), kb.cancel_to("admin:amb"))


@router.callback_query(F.data.regexp(r"^admin:amb:(\d+):ok$"))
async def amb_ok(call: CallbackQuery, state: FSMContext) -> None:
    await _start_terms_fsm(call, state, parse_id(call.data, -2), editing=False)


@router.callback_query(F.data.regexp(r"^admin:amb:(\d+):edit$"))
async def amb_edit(call: CallbackQuery, state: FSMContext) -> None:
    await _start_terms_fsm(call, state, parse_id(call.data, -2), editing=True)


@router.message(StateFilter(AdminFSM.amb_l1_bonus), F.text)
async def amb_l1_bonus(message: Message, state: FSMContext) -> None:
    await _capture_int(message, state, "l1_bonus", AdminFSM.amb_l1_percent, texts.amb_ask_l1_percent())


@router.message(StateFilter(AdminFSM.amb_l1_percent), F.text)
async def amb_l1_percent(message: Message, state: FSMContext) -> None:
    await _capture_int(message, state, "l1_percent", AdminFSM.amb_l2_bonus, texts.amb_ask_l2_bonus())


@router.message(StateFilter(AdminFSM.amb_l2_bonus), F.text)
async def amb_l2_bonus(message: Message, state: FSMContext) -> None:
    await _capture_int(message, state, "l2_bonus", AdminFSM.amb_l2_percent, texts.amb_ask_l2_percent())


@router.message(StateFilter(AdminFSM.amb_l2_percent), F.text)
async def amb_l2_percent(message: Message, state: FSMContext) -> None:
    await _capture_int(
        message, state, "l2_percent", AdminFSM.amb_promo_reward, texts.amb_ask_promo_reward()
    )


@router.message(StateFilter(AdminFSM.amb_promo_reward), F.text)
async def amb_promo_reward(message: Message, state: FSMContext) -> None:
    await _capture_int(
        message, state, "promo_reward", AdminFSM.amb_promo_max_uses, texts.amb_ask_promo_max_uses()
    )


@router.message(StateFilter(AdminFSM.amb_promo_max_uses), F.text)
async def amb_promo_max_uses(
    message: Message, session: AsyncSession, state: FSMContext, db_user: User
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно целое число ≥ 0.")
        return
    data = await state.get_data()
    data["promo_max_uses"] = int(raw)
    slot_id = int(data["slot_id"])
    try:
        if data.get("editing"):
            slot = await amb_service.update_slot_terms(
                session,
                slot_id=slot_id,
                l1_bonus=int(data["l1_bonus"]),
                l1_percent=int(data["l1_percent"]),
                l2_bonus=int(data["l2_bonus"]),
                l2_percent=int(data["l2_percent"]),
                promo_reward=int(data["promo_reward"]),
                promo_max_uses=int(data["promo_max_uses"]),
            )
            await audit.log_action(
                session, admin_id=db_user.id, action="ambassador.edit", target_type="ambassador", target_id=slot.id
            )
        else:
            slot = await amb_service.approve_slot(
                session,
                slot_id=slot_id,
                admin_id=db_user.id,
                l1_bonus=int(data["l1_bonus"]),
                l1_percent=int(data["l1_percent"]),
                l2_bonus=int(data["l2_bonus"]),
                l2_percent=int(data["l2_percent"]),
                promo_reward=int(data["promo_reward"]),
                promo_max_uses=int(data["promo_max_uses"]),
            )
            await audit.log_action(
                session,
                admin_id=db_user.id,
                action="ambassador.approve",
                target_type="ambassador",
                target_id=slot.id,
            )
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc.message}")
        return
    await state.clear()
    owner = await session.get(User, slot.user_id)
    await message.answer(
        texts.ambassador_card(slot, owner.display_name if owner else ""),
        reply_markup=kb.ambassador_card(slot),
    )


async def _capture_int(
    message: Message, state: FSMContext, key: str, next_state, next_prompt: str
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно целое число ≥ 0.")
        return
    await state.update_data(**{key: int(raw)})
    await state.set_state(next_state)
    await message.answer(next_prompt, reply_markup=kb.cancel_to("admin:amb"))


@router.callback_query(F.data.regexp(r"^admin:amb:(\d+):no$"))
async def amb_reject_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.amb_reject_reason)
    await state.set_data({"slot_id": parse_id(call.data, -2)})
    await safe_answer(call)
    await safe_edit(call.message, texts.amb_ask_reject(), kb.cancel_to("admin:amb"))


@router.message(StateFilter(AdminFSM.amb_reject_reason), F.text)
async def amb_reject_reason(
    message: Message, session: AsyncSession, state: FSMContext, db_user: User
) -> None:
    data = await state.get_data()
    try:
        slot = await amb_service.reject_slot(
            session,
            slot_id=int(data["slot_id"]),
            admin_id=db_user.id,
            reason=message.text or "",
        )
        await audit.log_action(
            session,
            admin_id=db_user.id,
            action="ambassador.reject",
            target_type="ambassador",
            target_id=slot.id,
        )
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc.message}")
        return
    await state.clear()
    await message.answer("Отклонено.", reply_markup=kb.ambassadors_hub(0, 0))


@router.callback_query(F.data.regexp(r"^admin:amb:(\d+):revoke$"))
async def amb_revoke(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    try:
        slot = await amb_service.revoke_slot(
            session, slot_id=parse_id(call.data, -2), admin_id=db_user.id
        )
        await audit.log_action(
            session, admin_id=db_user.id, action="ambassador.revoke", target_type="ambassador", target_id=slot.id
        )
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call)
    text, markup = await _card(session, slot.id)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:amb:(\d+):chat$"))
async def amb_chat_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.amb_chat_id)
    await state.set_data({"slot_id": parse_id(call.data, -2)})
    await safe_answer(call)
    await safe_edit(call.message, texts.amb_ask_chat_id(), kb.cancel_to("admin:amb"))


@router.message(StateFilter(AdminFSM.amb_chat_id), F.text)
async def amb_chat_id(message: Message, session: AsyncSession, state: FSMContext) -> None:
    raw = (message.text or "").strip().lstrip("-")
    if not raw.isdigit():
        await message.answer("Нужен числовой chat_id.")
        return
    data = await state.get_data()
    try:
        # keep leading minus for channel ids
        chat_id = int((message.text or "").strip())
        slot = await amb_service.set_chat_id(session, int(data["slot_id"]), chat_id)
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc.message}")
        return
    await state.clear()
    owner = await session.get(User, slot.user_id)
    await message.answer(
        texts.ambassador_card(slot, owner.display_name if owner else ""),
        reply_markup=kb.ambassador_card(slot),
    )


@router.callback_query(F.data.regexp(r"^admin:amb:(\d+):autopost:([01])$"))
async def amb_autopost(call: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    parts = (call.data or "").split(":")
    slot_id = int(parts[2])
    enable = parts[3] == "1"
    try:
        if enable:
            slot = await amb_service.enable_auto_post(session, bot, slot_id)
        else:
            slot = await amb_service.disable_auto_post(session, slot_id)
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call)
    owner = await session.get(User, slot.user_id)
    await safe_edit(
        call.message,
        texts.ambassador_card(slot, owner.display_name if owner else ""),
        kb.ambassador_card(slot),
    )
