from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.handlers.states import UserFSM
from app.bot.render import device_url_for
from app.bot.utils import button, parse_id, safe_answer, safe_edit
from app.config import Settings
from app.db.models import User, Withdrawal
from app.services import ledger, withdrawals
from app.services.errors import EconomyError

router = Router(name="withdraw")


async def _home_view(session: AsyncSession, user: User, settings: Settings):
    balance = await ledger.get_balance(session, user.id)
    held = await withdrawals.held_total(session, user.id)
    open_request = await withdrawals.open_withdrawal(session, user.id)
    device_url = device_url_for(user, settings) if settings.device_check_for_withdraw else None
    text = texts.withdraw_home(balance, held, settings, open_request)
    if device_url:
        text += "\n\n" + texts.device_notice(for_withdraw=True)
    markup = keyboards.withdraw_keyboard(
        balance,
        settings.withdraw_min,
        settings.withdraw_max,
        enabled=settings.withdraw_enabled and not user.is_banned,
        has_open=open_request is not None,
        device_url=device_url,
    )
    return text, markup


@router.callback_query(F.data == "menu:withdraw")
async def menu_withdraw(
    call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings, state: FSMContext
) -> None:
    await state.clear()
    text, markup = await _home_view(session, db_user, settings)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


async def _apply(session: AsyncSession, user: User, amount: int, settings: Settings) -> str:
    try:
        wd = await withdrawals.apply(session, user=user, amount=amount, settings=settings)
    except EconomyError as exc:
        return f"⚠️ {exc.message}"
    return texts.withdraw_created(wd)


@router.callback_query(F.data.startswith("wd:amt:"))
async def withdraw_amount(
    call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings
) -> None:
    amount = parse_id(call.data)
    text = await _apply(session, db_user, amount, settings)
    await safe_answer(call)
    await safe_edit(call.message, text, keyboards.back_home([button("📄 Мои заявки", "wd:list")]))


@router.callback_query(F.data == "wd:custom")
async def withdraw_custom(
    call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings, state: FSMContext
) -> None:
    balance = await ledger.get_balance(session, db_user.id)
    await state.set_state(UserFSM.withdraw_amount)
    await safe_answer(call)
    await safe_edit(
        call.message, texts.withdraw_custom_prompt(balance, settings), keyboards.cancel_only("menu:withdraw")
    )


@router.message(StateFilter(UserFSM.withdraw_amount), F.text)
async def withdraw_custom_amount(
    message: Message, session: AsyncSession, db_user: User, settings: Settings, state: FSMContext
) -> None:
    raw = (message.text or "").strip().replace(" ", "")
    if not raw.isdigit():
        await message.answer(
            "Введите сумму числом, например <code>120</code>.",
            reply_markup=keyboards.cancel_only("menu:withdraw"),
        )
        return
    await state.clear()
    text = await _apply(session, db_user, int(raw), settings)
    await message.answer(text, reply_markup=keyboards.back_home([button("📄 Мои заявки", "wd:list")]))


@router.callback_query(F.data == "wd:list")
async def withdraw_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    items = await withdrawals.list_user_withdrawals(session, db_user.id, limit=10)
    await safe_answer(call)
    await safe_edit(call.message, texts.withdraw_list(items), keyboards.withdraw_list_menu(items))


@router.callback_query(F.data.startswith("wd:cancel:"))
async def withdraw_cancel(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    wd = await session.get(Withdrawal, parse_id(call.data))
    if wd is None:
        await safe_answer(call, "Заявка не найдена", alert=True)
        return
    try:
        await withdrawals.cancel(session, withdrawal=wd, user=db_user)
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call, "Заявка отменена, Stars возвращены", alert=True)
    items = await withdrawals.list_user_withdrawals(session, db_user.id, limit=10)
    await safe_edit(call.message, texts.withdraw_list(items), keyboards.withdraw_list_menu(items))
