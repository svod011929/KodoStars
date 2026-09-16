from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.handlers.states import UserFSM
from app.bot.utils import safe_answer, safe_edit
from app.config import Settings
from app.db.models import User
from app.services import promo as promo_service
from app.services.errors import EconomyError

router = Router(name="promo")


@router.callback_query(F.data == "menu:promo")
async def menu_promo(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFSM.promo_code)
    await safe_answer(call)
    await safe_edit(call.message, texts.promo_prompt(), keyboards.cancel_only("menu:home"))


@router.message(StateFilter(UserFSM.promo_code), F.text)
async def promo_enter(
    message: Message, session: AsyncSession, db_user: User, settings: Settings, state: FSMContext
) -> None:
    code = (message.text or "").strip()
    if code.startswith("/"):
        await state.clear()
        return
    try:
        promo, amount = await promo_service.redeem(session, user=db_user, code=code, settings=settings)
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc.message}", reply_markup=keyboards.cancel_only("menu:home"))
        return
    await state.clear()
    await message.answer(texts.promo_ok(promo, amount), reply_markup=keyboards.back_home())
