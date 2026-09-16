from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.render import render_home
from app.bot.utils import safe_answer, safe_edit
from app.config import Settings
from app.db.models import User
from app.op.base import OpContext
from app.op.gate import OpGate
from app.services import referrals, users
from app.services.antifraud import bump_activity

router = Router(name="start")


def _ctx(user: User, chat_id: int, bot: Bot) -> OpContext:
    return OpContext(
        user_id=user.id,
        chat_id=chat_id,
        first_name=user.first_name,
        username=user.username,
        language_code=user.language_code or "ru",
        is_premium=user.is_premium,
        bot=bot,
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
    bot: Bot,
    op_gate: OpGate,
    state: FSMContext,
    bot_username: str,
    is_admin: bool,
) -> None:
    await state.clear()
    payload = ""
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            payload = parts[1]
    first_start = users.mark_started(db_user)
    await referrals.attach_referrer(
        session, user=db_user, payload=payload, settings=settings, first_start=first_start
    )
    if db_user.is_banned:
        await message.answer(texts.banned(db_user.ban_reason or "бан", settings.support_contact))
        return
    if not is_admin:
        result = await op_gate.enforce(_ctx(db_user, message.chat.id, bot), session, settings=settings)
        if not result.allowed:
            await message.answer(
                texts.op_blocked(result.provider, result.message),
                reply_markup=keyboards.op_keyboard(result.sponsors),
            )
            return
        db_user.last_op_ok_at = datetime.now(UTC)
    await bump_activity(session, db_user, 1)
    await referrals.activate_if_ready(session, user=db_user, settings=settings)
    text, markup = await render_home(
        session, db_user, bot_username=bot_username, is_admin=is_admin, settings=settings
    )
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "op:verify")
async def op_verify(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
    bot: Bot,
    op_gate: OpGate,
    bot_username: str,
    is_admin: bool,
) -> None:
    if db_user.is_banned:
        await safe_answer(call, texts.banned_short(), alert=True)
        return
    chat_id = call.message.chat.id if call.message else db_user.id
    result = await op_gate.enforce(_ctx(db_user, chat_id, bot), session, verify=True, settings=settings)
    if not result.allowed:
        await safe_answer(call, "Ещё не все подписки засчитаны", alert=True)
        await safe_edit(
            call.message,
            texts.op_blocked(result.provider, result.message),
            keyboards.op_keyboard(result.sponsors),
        )
        return
    db_user.last_op_ok_at = datetime.now(UTC)
    await bump_activity(session, db_user, 1)
    await referrals.activate_if_ready(session, user=db_user, settings=settings)
    text, markup = await render_home(
        session, db_user, bot_username=bot_username, is_admin=is_admin, settings=settings
    )
    await safe_answer(call, "Доступ открыт ✅")
    await safe_edit(call.message, text, markup)
