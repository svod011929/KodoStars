from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import PAGE_SIZE, button, parse_id, safe_answer, safe_edit
from app.config import Settings
from app.db.models import BoostProduct, LedgerKind, PaymentStatus, User
from app.services import antifraud, audit, devices, events, ledger, payments, referrals, users, withdrawals
from app.services.access import AccessRegistry
from app.services.errors import EconomyError

router = Router(name="admin.users")


async def render_user_card(
    session: AsyncSession, user: User, access: AccessRegistry, settings: Settings | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    balance = await ledger.get_balance(session, user.id)
    linked = await devices.linked_accounts(session, user)
    held = await withdrawals.held_total(session, user.id)
    refs = await referrals.referral_stats(session, user.id)
    activated = await referrals.activated_invite_count(session, user.id)
    ref_earned = await referrals.referral_earnings(session, user.id)
    pays = await payments.list_payments(session, user_id=user.id, limit=200)
    pays_xtr = sum(p.xtr_amount for p in pays if p.status == PaymentStatus.PAID.value)
    totals = await withdrawals.list_user_withdrawals(session, user.id, limit=200)
    sent = sum(w.amount for w in totals if w.status == "sent")
    open_wd = await withdrawals.open_withdrawal(session, user.id)
    fraud_count = await antifraud.count_events(session, user_id=user.id)
    referrer = await session.get(User, user.referred_by_id) if user.referred_by_id else None
    text = texts.user_card(
        user,
        balance=balance,
        held=held,
        refs=refs,
        activated=activated,
        ref_earned=ref_earned,
        payments_count=len(pays),
        payments_xtr=pays_xtr,
        withdrawals_sent=sent,
        open_wd=open_wd,
        fraud_count=fraud_count,
        referrer=referrer,
        is_admin=access.is_admin(user.id),
        linked=linked,
        device_check_active=settings.device_check_active if settings is not None else None,
    )
    return text, kb.user_card(user, is_owner_viewer=True, open_wd=open_wd)


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):trust:(0|1)$"))
async def user_trust(
    call: CallbackQuery, session: AsyncSession, access: AccessRegistry, settings: Settings
) -> None:
    parts = (call.data or "").split(":")
    user = await session.get(User, int(parts[2]))
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    trusted = parts[4] == "1"
    await devices.set_trusted(session, user, trusted)
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="user.trust",
        target_type="user",
        target_id=user.id,
        trusted=trusted,
    )
    if trusted:
        # Trust may unlock the pending referral bonus right away.
        await referrals.activate_if_ready(session, user=user, settings=settings)
    text, markup = await render_user_card(session, user, access, settings)
    await safe_answer(call, "Доверенный" if trusted else "Доверие снято")
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "admin:users")
async def users_home(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(AdminFSM.user_search)
    recent = await users.recent_users(session, limit=5)
    total = await users.count_users(session)
    await safe_answer(call)
    await safe_edit(call.message, texts.users_home(recent, total), kb.users_home(recent))


@router.message(StateFilter(AdminFSM.user_search), F.text)
async def users_search(message: Message, session: AsyncSession, access: AccessRegistry) -> None:
    query = (message.text or "").strip()
    user = await users.find_user(session, query)
    if user is None:
        matches = await users.search_users(session, query, limit=1)
        user = matches[0] if matches else None
    if user is None:
        await message.answer(texts.user_not_found(query))
        return
    text, markup = await render_user_card(session, user, access)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^admin:u:(\d+)$"))
async def user_card(
    call: CallbackQuery, session: AsyncSession, access: AccessRegistry, state: FSMContext
) -> None:
    await state.set_state(AdminFSM.user_search)
    user = await session.get(User, parse_id(call.data))
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    text, markup = await render_user_card(session, user, access)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):adj$"))
async def user_adjust_start(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    user = await session.get(User, parse_id(call.data, -2))
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    await state.set_state(AdminFSM.user_adjust)
    await state.update_data(uid=user.id)
    balance = await ledger.get_balance(session, user.id)
    await safe_answer(call)
    await safe_edit(call.message, texts.user_adjust_prompt(user, balance), kb.cancel_to(f"admin:u:{user.id}"))


@router.message(StateFilter(AdminFSM.user_adjust), F.text)
async def user_adjust_apply(
    message: Message, session: AsyncSession, state: FSMContext, access: AccessRegistry
) -> None:
    data = await state.get_data()
    user = await session.get(User, int(data.get("uid", 0)))
    if user is None:
        await state.set_state(AdminFSM.user_search)
        await message.answer("Пользователь не найден.")
        return
    raw = (message.text or "").strip()
    parts = raw.split(maxsplit=1)
    amount_raw = parts[0].replace("−", "-")
    if not amount_raw.lstrip("+-").isdigit() or int(amount_raw) == 0:
        await message.answer("Формат: <code>+50 комментарий</code> или <code>-20 комментарий</code>.")
        return
    amount = int(amount_raw)
    reason = parts[1].strip() if len(parts) > 1 else ""
    try:
        await ledger.append_entry(
            session,
            user_id=user.id,
            amount=amount,
            kind=LedgerKind.ADMIN_ADJUST,
            reference=f"admin:{message.from_user.id}",
            extra={"reason": reason, "admin_id": message.from_user.id},
            allow_negative=True,
        )
    except EconomyError as exc:
        await message.answer(exc.message)
        return
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="user.adjust",
        target_type="user",
        target_id=user.id,
        amount=amount,
        reason=reason,
    )
    events.emit(session, "balance_adjusted", user_id=user.id, amount=amount, reason=reason)
    await state.set_state(AdminFSM.user_search)
    text, markup = await render_user_card(session, user, access)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):ban$"))
async def user_ban_start(
    call: CallbackQuery, session: AsyncSession, state: FSMContext, access: AccessRegistry
) -> None:
    user = await session.get(User, parse_id(call.data, -2))
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    if access.is_admin(user.id):
        await safe_answer(call, "Нельзя банить администратора", alert=True)
        return
    await state.set_state(AdminFSM.user_ban_reason)
    await state.update_data(uid=user.id)
    await safe_answer(call)
    await safe_edit(call.message, texts.user_ban_prompt(user), kb.cancel_to(f"admin:u:{user.id}"))


@router.message(StateFilter(AdminFSM.user_ban_reason), F.text)
async def user_ban_apply(
    message: Message, session: AsyncSession, state: FSMContext, access: AccessRegistry
) -> None:
    data = await state.get_data()
    user = await session.get(User, int(data.get("uid", 0)))
    await state.set_state(AdminFSM.user_search)
    if user is None:
        await message.answer("Пользователь не найден.")
        return
    reason = (message.text or "").strip() or "Нарушение правил"
    await antifraud.set_ban(session, user, banned=True, reason=reason, admin_id=message.from_user.id)
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="user.ban",
        target_type="user",
        target_id=user.id,
        reason=reason,
    )
    text, markup = await render_user_card(session, user, access)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):unban$"))
async def user_unban(call: CallbackQuery, session: AsyncSession, access: AccessRegistry) -> None:
    user = await session.get(User, parse_id(call.data, -2))
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    await antifraud.set_ban(session, user, banned=False, reason="", admin_id=call.from_user.id)
    await audit.log_action(
        session, admin_id=call.from_user.id, action="user.unban", target_type="user", target_id=user.id
    )
    text, markup = await render_user_card(session, user, access)
    await safe_answer(call, "Разбанен")
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):note$"))
async def user_note_start(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    user = await session.get(User, parse_id(call.data, -2))
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    await state.set_state(AdminFSM.user_note)
    await state.update_data(uid=user.id)
    await safe_answer(call)
    await safe_edit(call.message, texts.user_note_prompt(user), kb.cancel_to(f"admin:u:{user.id}"))


@router.message(StateFilter(AdminFSM.user_note), F.text)
async def user_note_apply(
    message: Message, session: AsyncSession, state: FSMContext, access: AccessRegistry
) -> None:
    data = await state.get_data()
    user = await session.get(User, int(data.get("uid", 0)))
    await state.set_state(AdminFSM.user_search)
    if user is None:
        await message.answer("Пользователь не найден.")
        return
    text_raw = (message.text or "").strip()
    user.admin_note = None if text_raw == "-" else text_raw[:1000]
    await session.flush()
    await audit.log_action(
        session, admin_id=message.from_user.id, action="user.note", target_type="user", target_id=user.id
    )
    text, markup = await render_user_card(session, user, access)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):msg$"))
async def user_message_start(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    user = await session.get(User, parse_id(call.data, -2))
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    await state.set_state(AdminFSM.user_message)
    await state.update_data(uid=user.id)
    await safe_answer(call)
    await safe_edit(call.message, texts.user_message_prompt(user), kb.cancel_to(f"admin:u:{user.id}"))


@router.message(StateFilter(AdminFSM.user_message))
async def user_message_send(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    uid = int(data.get("uid", 0))
    await state.set_state(AdminFSM.user_search)
    try:
        await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
    except TelegramAPIError as exc:
        await message.answer(f"Не доставлено: {exc}")
        return
    await audit.log_action(
        session, admin_id=message.from_user.id, action="user.message", target_type="user", target_id=uid
    )
    await message.answer("Отправлено ✅", reply_markup=kb.user_sub(uid))


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):ledger:(\d+)$"))
async def user_ledger(call: CallbackQuery, session: AsyncSession) -> None:
    uid = parse_id(call.data, 2)
    page = parse_id(call.data, -1)
    user = await session.get(User, uid)
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    total = await ledger.count_entries(session, uid)
    entries = await ledger.history(session, uid, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.user_ledger(user, entries, page, total, PAGE_SIZE),
        kb.user_ledger(uid, page, total),
    )


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):refs$"))
async def user_refs(call: CallbackQuery, session: AsyncSession) -> None:
    uid = parse_id(call.data, -2)
    user = await session.get(User, uid)
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    refs = await referrals.list_referrals(session, uid, level=1, limit=20)
    await safe_answer(call)
    await safe_edit(call.message, texts.user_refs(user, refs), kb.user_sub(uid))


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):fraud(?::(\d+))?$"))
async def user_fraud(call: CallbackQuery, session: AsyncSession) -> None:
    parts = (call.data or "").split(":")
    uid = int(parts[2])
    page = int(parts[4]) if len(parts) > 4 else 0
    user = await session.get(User, uid)
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    total = await antifraud.count_events(session, user_id=uid)
    items = await antifraud.recent_events(session, user_id=uid, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    await safe_answer(call)
    await safe_edit(
        call.message, texts.fraud_events(items, page, total, PAGE_SIZE, user), kb.fraud(page, total, uid)
    )


@router.callback_query(F.data.regexp(r"^admin:u:(\d+):pays$"))
async def user_payments(call: CallbackQuery, session: AsyncSession) -> None:
    uid = parse_id(call.data, -2)
    items = await payments.list_payments(session, user_id=uid, limit=PAGE_SIZE)
    total = await payments.count_payments(session, user_id=uid)
    titles = await _product_titles(session, items)
    revenue = sum(p.xtr_amount for p in items if p.status == PaymentStatus.PAID.value)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.payments_home(items, titles, 0, total, PAGE_SIZE, revenue),
        kb.user_sub(
            uid, *[[button(f"#{p.id} · {p.xtr_amount} XTR", f"admin:pay:view:{p.id}")] for p in items]
        ),
    )


async def _product_titles(session: AsyncSession, items) -> dict[int, str]:
    titles: dict[int, str] = {}
    for item in items:
        if item.product_id and item.product_id not in titles:
            product = await session.get(BoostProduct, item.product_id)
            titles[item.product_id] = product.title if product else "—"
    return titles
