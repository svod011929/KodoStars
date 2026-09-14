from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.config import Settings
from app.db.models import User
from app.services import ledger, withdrawals
from app.services.errors import UserBanned, WithdrawalError

router = Router(name="withdraw")


@router.callback_query(F.data == "menu:withdraw")
async def menu_withdraw(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    balance = await ledger.get_balance(session, db_user.id)
    await call.answer()
    if call.message:
        await call.message.edit_text(
            texts.withdraw_home(balance, settings.withdraw_min, settings.withdraw_cooldown_hours),
            reply_markup=keyboards.withdraw_keyboard(balance, settings.withdraw_min),
        )


@router.callback_query(F.data.startswith("wd:amt:"))
async def withdraw_amount(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    amount = int((call.data or "0").split(":")[-1])
    try:
        wd = await withdrawals.apply(
            session, user=db_user, amount=amount, settings=settings
        )
        text = texts.withdraw_created(wd)
    except (WithdrawalError, UserBanned) as exc:
        text = exc.message
    await call.answer()
    if call.message:
        await call.message.edit_text(text, reply_markup=keyboards.back_home())
