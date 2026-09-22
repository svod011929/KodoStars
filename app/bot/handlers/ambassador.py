"""User ambassador program: apply, claim daily promo, optional publish."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.handlers.states import UserFSM
from app.bot.utils import parse_id, safe_answer, safe_edit
from app.db.models import AMBASSADOR_KIND_LABELS, User
from app.services import ambassadors as amb_service
from app.services.errors import EconomyError

router = Router(name="ambassador")


@router.callback_query(F.data == "menu:amb")
async def menu_amb(call: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext) -> None:
    await state.clear()
    slots = await amb_service.list_user_slots(session, db_user.id)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.ambassador_hub(len(slots)),
        keyboards.ambassador_home(slots),
    )


@router.callback_query(F.data == "amb:new")
async def amb_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(call)
    await safe_edit(call.message, texts.ambassador_pick_kind(), keyboards.ambassador_kind_pick())


@router.callback_query(F.data.regexp(r"^amb:kind:(channel|chat|bot)$"))
async def amb_kind(call: CallbackQuery, state: FSMContext) -> None:
    kind = (call.data or "").rsplit(":", 1)[-1]
    await state.set_state(UserFSM.amb_link)
    await state.set_data({"kind": kind})
    label = AMBASSADOR_KIND_LABELS.get(kind, kind)
    await safe_answer(call)
    await safe_edit(call.message, texts.ambassador_ask_link(label), keyboards.cancel_only("menu:amb"))


@router.message(StateFilter(UserFSM.amb_link), F.text)
async def amb_link_enter(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        return
    await state.update_data(invite_link=raw)
    await state.set_state(UserFSM.amb_title)
    await message.answer(texts.ambassador_ask_title(), reply_markup=keyboards.cancel_only("menu:amb"))


@router.message(StateFilter(UserFSM.amb_title), F.text)
async def amb_title_enter(
    message: Message, session: AsyncSession, db_user: User, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        return
    data = await state.get_data()
    try:
        slot = await amb_service.submit_application(
            session,
            user=db_user,
            kind=str(data.get("kind") or ""),
            title=raw,
            invite_link=str(data.get("invite_link") or ""),
        )
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc.message}", reply_markup=keyboards.cancel_only("menu:amb"))
        return
    await state.clear()
    slots = await amb_service.list_user_slots(session, db_user.id)
    await message.answer(texts.ambassador_submitted(slot.title))
    await message.answer(texts.ambassador_hub(len(slots)), reply_markup=keyboards.ambassador_home(slots))


@router.callback_query(F.data.regexp(r"^amb:slot:(\d+)$"))
async def amb_slot(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    slot = await amb_service.get_slot(session, parse_id(call.data))
    if slot.user_id != db_user.id:
        await safe_answer(call, "Не ваш слот", alert=True)
        return
    today = await amb_service.todays_promo(session, slot.id)
    code = today.code if today else None
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.ambassador_slot_text(slot, code),
        keyboards.ambassador_slot_card(slot, today_code=code),
    )


@router.callback_query(F.data.regexp(r"^amb:claim:(\d+)$"))
async def amb_claim(call: CallbackQuery, session: AsyncSession, db_user: User, bot: Bot) -> None:
    slot_id = parse_id(call.data)
    try:
        promo = await amb_service.claim_daily_promo(session, slot_id=slot_id, user_id=db_user.id)
        slot = await amb_service.get_slot(session, slot_id)
        posted = False
        if slot.promo_auto_post:
            try:
                await amb_service.publish_promo(bot, slot, promo)
                posted = True
            except EconomyError:
                slot.promo_auto_post = False
                await session.flush()
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.ambassador_promo_ready(promo.code, promo.reward, promo.max_uses, posted),
        keyboards.ambassador_slot_card(slot, today_code=promo.code),
    )


@router.callback_query(F.data.regexp(r"^amb:post:(\d+)$"))
async def amb_post(call: CallbackQuery, session: AsyncSession, db_user: User, bot: Bot) -> None:
    slot_id = parse_id(call.data)
    try:
        slot = await amb_service.get_slot(session, slot_id)
        if slot.user_id != db_user.id:
            raise EconomyError("Не ваш слот")
        promo = await amb_service.todays_promo(session, slot_id)
        if promo is None:
            raise EconomyError("Сначала получите промокод на сегодня")
        await amb_service.publish_promo(bot, slot, promo)
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call, "Опубликовано", alert=True)
