from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import emoji as pe, keyboards, texts
from app.bot.render import device_url_for, render_home
from app.bot.utils import safe_answer, safe_edit
from app.config import Settings
from app.db.models import User
from app.op.base import OpContext, OpResult
from app.op.gate import OpGate
from app.services import botohub_views, piarflow_quality, referrals, users
from app.services.antifraud import bump_activity
from app.services.devices import op_access_block_reason

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


async def _gate_device_or_op(
    *,
    user: User,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
    chat_id: int,
    op_gate: OpGate,
    verify: bool = False,
) -> tuple[str, str | None, object | None, OpResult | None]:
    """Run twin/device checks first; only then call PiarFlow."""
    block = op_access_block_reason(user, settings)
    if block == "device":
        url = device_url_for(user, settings) or settings.web_url("verify")
        return "device", texts.op_need_device(), keyboards.device_gate_keyboard(url), None
    if block == "twink":
        return "twink", texts.op_twink_blocked(settings.support_contact), None, None
    result = await op_gate.enforce(
        _ctx(user, chat_id, bot), session, verify=verify, settings=settings
    )
    await piarflow_quality.record_from_op_result(session, user.id, result)
    if result.allowed:
        return "ok", None, None, result
    return (
        "op",
        texts.op_blocked(result.provider, result.message),
        keyboards.op_keyboard(result.sponsors),
        result,
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
        await message.answer(
            pe.premiumize(texts.banned(db_user.ban_reason or "бан", settings.support_contact))
        )
        return
    if not is_admin:
        kind, text, markup, _result = await _gate_device_or_op(
            user=db_user,
            settings=settings,
            session=session,
            bot=bot,
            chat_id=message.chat.id,
            op_gate=op_gate,
        )
        if kind != "ok":
            await message.answer(pe.premiumize(text) if text else text, reply_markup=markup)
            return
        db_user.last_op_ok_at = datetime.now(UTC)
    await bump_activity(session, db_user, 1)
    await referrals.activate_if_ready(session, user=db_user, settings=settings)
    text, markup = await render_home(
        session, db_user, bot_username=bot_username, is_admin=is_admin, settings=settings
    )
    await message.answer(pe.premiumize(text) if text else text, reply_markup=markup)
    if first_start:
        botohub_views.schedule_hi(db_user.id, settings)


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
    kind, text, markup, _result = await _gate_device_or_op(
        user=db_user,
        settings=settings,
        session=session,
        bot=bot,
        chat_id=chat_id,
        op_gate=op_gate,
        verify=True,
    )
    if kind != "ok":
        alert = "Сначала подтвердите устройство" if kind == "device" else "Доступ ограничен"
        if kind == "op":
            alert = "Ещё не все подписки засчитаны"
        await safe_answer(call, alert, alert=True)
        await safe_edit(call.message, text, markup)
        return
    db_user.last_op_ok_at = datetime.now(UTC)
    await bump_activity(session, db_user, 1)
    await referrals.activate_if_ready(session, user=db_user, settings=settings)
    home_text, home_markup = await render_home(
        session, db_user, bot_username=bot_username, is_admin=is_admin, settings=settings
    )
    await safe_answer(call, "Доступ открыт")
    await safe_edit(call.message, home_text, home_markup)
