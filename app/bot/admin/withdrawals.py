from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import PAGE_SIZE, parse_id, safe_answer, safe_edit
from app.config import Settings
from app.db.models import OPEN_WITHDRAWAL_STATUSES, User, Withdrawal, WithdrawalStatus
from app.services import antifraud, audit, devices, fragment, ledger, referrals, withdrawals
from app.services.errors import WithdrawalError
from app.services.fragment import FragmentError

router = Router(name="admin.withdrawals")

FILTERS: dict[str, tuple[str, ...]] = {
    "open": OPEN_WITHDRAWAL_STATUSES,
    "pending": (WithdrawalStatus.PENDING.value,),
    "approved": (WithdrawalStatus.APPROVED_MANUAL.value,),
    "history": (
        WithdrawalStatus.SENT.value,
        WithdrawalStatus.REJECTED.value,
        WithdrawalStatus.CANCELLED.value,
    ),
}


async def render_card(session: AsyncSession, wd: Withdrawal) -> tuple[str, InlineKeyboardMarkup]:
    user = await session.get(User, wd.user_id)
    balance = await ledger.get_balance(session, wd.user_id)
    refs = await referrals.referral_stats(session, wd.user_id)
    activated = await referrals.activated_invite_count(session, wd.user_id)
    history = await withdrawals.list_user_withdrawals(session, wd.user_id, limit=200)
    sent_before = sum(item.amount for item in history if item.status == "sent" and item.id != wd.id)
    fraud_count = await antifraud.count_events(session, user_id=wd.user_id)
    linked = await devices.linked_accounts(session, user) if user is not None else []
    text = texts.withdrawal_card(wd, user, balance, refs, activated, sent_before, fraud_count, linked)
    return text, kb.withdrawal_card(wd)


@router.callback_query(F.data == "admin:wd")
async def wd_home(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    counts = await withdrawals.totals(session)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.withdrawals_home(counts),
        kb.withdrawals_home(counts.get("pending_count", 0), counts.get("approved_manual_count", 0)),
    )


@router.callback_query(F.data.regexp(r"^admin:wd:list:(\w+):(\d+)$"))
async def wd_list(call: CallbackQuery, session: AsyncSession) -> None:
    parts = (call.data or "").split(":")
    filter_name = parts[3]
    page = int(parts[4])
    statuses = FILTERS.get(filter_name, OPEN_WITHDRAWAL_STATUSES)
    total = await withdrawals.count_queue(session, statuses)
    items = await withdrawals.list_queue(session, statuses, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    names: dict[int, str] = {}
    for item in items:
        if item.user_id not in names:
            user = await session.get(User, item.user_id)
            names[item.user_id] = user.display_name if user else str(item.user_id)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.withdrawals_list(items, filter_name, page, total, PAGE_SIZE),
        kb.withdrawals_list(items, names, filter_name, page, total),
    )


@router.callback_query(F.data.regexp(r"^admin:wd:view:(\d+)$"))
async def wd_view(call: CallbackQuery, session: AsyncSession) -> None:
    wd = await session.get(Withdrawal, parse_id(call.data))
    if wd is None:
        await safe_answer(call, "Заявка не найдена", alert=True)
        return
    text, markup = await render_card(session, wd)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:wd:ok:(\d+)$"))
async def wd_approve(call: CallbackQuery, session: AsyncSession) -> None:
    wd = await session.get(Withdrawal, parse_id(call.data))
    if wd is None:
        await safe_answer(call, "Заявка не найдена", alert=True)
        return
    try:
        await withdrawals.approve_manual(session, withdrawal=wd, admin_id=call.from_user.id)
    except WithdrawalError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="withdrawal.approve",
        target_type="withdrawal",
        target_id=wd.id,
        amount=wd.amount,
    )
    text, markup = await render_card(session, wd)
    await safe_answer(call, "Согласовано. Отправьте Stars и подтвердите.")
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:wd:no:(\d+)$"))
async def wd_reject_start(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    wd = await session.get(Withdrawal, parse_id(call.data))
    if wd is None:
        await safe_answer(call, "Заявка не найдена", alert=True)
        return
    if wd.status not in OPEN_WITHDRAWAL_STATUSES:
        await safe_answer(call, "Заявка уже закрыта", alert=True)
        return
    await state.set_state(AdminFSM.wd_reject_reason)
    await state.update_data(wd_id=wd.id)
    await safe_answer(call)
    await safe_edit(call.message, texts.reject_reason_prompt(wd), kb.cancel_to(f"admin:wd:view:{wd.id}"))


@router.message(StateFilter(AdminFSM.wd_reject_reason), F.text)
async def wd_reject_apply(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    wd = await session.get(Withdrawal, int(data.get("wd_id", 0)))
    if wd is None:
        await message.answer("Заявка не найдена.")
        return
    reason = (message.text or "").strip()
    try:
        await withdrawals.reject(session, withdrawal=wd, admin_id=message.from_user.id, note=reason)
    except WithdrawalError as exc:
        await message.answer(exc.message)
        return
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="withdrawal.reject",
        target_type="withdrawal",
        target_id=wd.id,
        reason=reason,
    )
    text, markup = await render_card(session, wd)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^admin:wd:sent:(\d+)$"))
async def wd_sent(call: CallbackQuery, session: AsyncSession) -> None:
    wd = await session.get(Withdrawal, parse_id(call.data))
    if wd is None:
        await safe_answer(call, "Заявка не найдена", alert=True)
        return
    try:
        await withdrawals.confirm_sent(session, withdrawal=wd, admin_id=call.from_user.id)
    except WithdrawalError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="withdrawal.sent",
        target_type="withdrawal",
        target_id=wd.id,
        amount=wd.amount,
        gift_id=wd.gift_id,
    )
    text, markup = await render_card(session, wd)
    await safe_answer(call, "Выплата подтверждена")
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.regexp(r"^admin:wd:fragment:(\d+)$"))
async def wd_send_fragment(
    call: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    wd = await session.get(Withdrawal, parse_id(call.data))
    if wd is None:
        await safe_answer(call, "Заявка не найдена", alert=True)
        return
    if wd.status != WithdrawalStatus.APPROVED_MANUAL.value:
        await safe_answer(call, "Сначала согласуйте заявку", alert=True)
        return
    user = await session.get(User, wd.user_id)
    if user is None:
        await safe_answer(call, "Пользователь не найден", alert=True)
        return
    await safe_answer(call, "Отправляю Stars через Fragment…")
    try:
        purchase = await fragment.buy_stars(settings, username=user.username, amount=wd.amount)
    except FragmentError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    try:
        await withdrawals.confirm_sent(session, withdrawal=wd, admin_id=call.from_user.id)
    except WithdrawalError as exc:
        await safe_answer(
            call,
            f"Stars отправлены (@{purchase.username}), но статус не обновлён: {exc.message}. "
            "Отметьте вручную.",
            alert=True,
        )
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="withdrawal.sent",
        target_type="withdrawal",
        target_id=wd.id,
        amount=wd.amount,
        gift_id=wd.gift_id,
        via="fragment",
        fragment_username=purchase.username,
    )
    text, markup = await render_card(session, wd)
    await safe_edit(call.message, text, markup)
    await safe_answer(call, f"Отправлено @{purchase.username} · {purchase.amount}⭐")

