from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.render import render_home
from app.config import Settings
from app.db.models import User
from app.op.base import OpContext
from app.op.gate import OpGate
from app.services import referrals
from app.services.antifraud import bump_activity

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
    bot: Bot,
    op_gate: OpGate,
) -> None:
    payload = ""
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            payload = parts[1]
    await referrals.attach_referrer(
        session, user=db_user, payload=payload, settings=settings
    )
    if db_user.is_banned:
        await message.answer(texts.banned(db_user.ban_reason or "бан"))
        return
    if db_user.id not in settings.admin_ids:
        ctx = OpContext(
            user_id=db_user.id,
            chat_id=message.chat.id,
            first_name=db_user.first_name,
            username=db_user.username,
            language_code=db_user.language_code or "ru",
            is_premium=db_user.is_premium,
            bot=bot,
        )
        result = await op_gate.enforce(ctx, session)
        if not result.allowed:
            await message.answer(
                texts.op_blocked(result.provider, result.message),
                reply_markup=keyboards.op_keyboard(result.sponsors),
            )
            return
        db_user.last_op_ok_at = datetime.now(UTC)
        await bump_activity(session, db_user, 1)
        await referrals.activate_if_ready(session, user=db_user, settings=settings)
    me = await bot.get_me()
    text, markup = await render_home(session, db_user, settings, me.username or "bot")
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "op:verify")
async def op_verify(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
    bot: Bot,
    op_gate: OpGate,
) -> None:
    if db_user.is_banned:
        await call.answer("Доступ закрыт", show_alert=True)
        return
    ctx = OpContext(
        user_id=db_user.id,
        chat_id=call.message.chat.id if call.message else db_user.id,
        first_name=db_user.first_name,
        username=db_user.username,
        language_code=db_user.language_code or "ru",
        is_premium=db_user.is_premium,
        bot=bot,
    )
    result = await op_gate.enforce(ctx, session, verify=True)
    if not result.allowed:
        await call.answer("Ещё не все подписки засчитаны", show_alert=True)
        if call.message:
            await call.message.edit_text(
                texts.op_blocked(result.provider, result.message),
                reply_markup=keyboards.op_keyboard(result.sponsors),
            )
        return
    db_user.last_op_ok_at = datetime.now(UTC)
    await bump_activity(session, db_user, 1)
    await referrals.activate_if_ready(session, user=db_user, settings=settings)
    me = await bot.get_me()
    text, markup = await render_home(session, db_user, settings, me.username or "bot")
    await call.answer("Доступ открыт")
    if call.message:
        await call.message.edit_text(text, reply_markup=markup)
