from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import emoji as pe
from app.bot import keyboards, texts
from app.bot.render import render_home
from app.bot.utils import safe_answer, safe_edit
from app.config import Settings
from app.db.models import User
from app.op.base import OpContext, OpResult
from app.op.gate import OpGate
from app.services import botohub_views, campaigns, greetings, referrals, users
from app.services import promo as promo_service
from app.services.antifraud import bump_activity
from app.services.errors import EconomyError

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


async def _gate_op(
    *,
    user: User,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
    chat_id: int,
    op_gate: OpGate,
    verify: bool = False,
) -> tuple[str, str | None, object | None, OpResult | None]:
    """Verified → PiarFlow then Tgrass; unverified → Tgrass only."""
    ctx = _ctx(user, chat_id, bot)
    result = await op_gate.enforce(
        ctx, session, verify=verify, settings=settings, user=user
    )
    if result.allowed:
        return "ok", None, None, result
    return (
        "op",
        texts.op_blocked(
            result.provider, result.message, l1_bonus=settings.referral_l1_bonus
        ),
        keyboards.op_keyboard(result.sponsors),
        result,
    )


async def _try_redeem_pending_promo(
    *,
    session: AsyncSession,
    user: User,
    settings: Settings,
    state: FSMContext,
    reply: Message | CallbackQuery,
) -> bool:
    """Redeem ``pending_promo`` from FSM if set. Returns True when a redeem was attempted."""
    data = await state.get_data()
    code = data.get("pending_promo")
    if not code:
        return False
    await state.update_data(pending_promo=None)
    try:
        promo, amount = await promo_service.redeem(
            session,
            user=user,
            code=str(code),
            settings=settings,
            skip_cooldown=True,
        )
    except EconomyError as exc:
        text = f"⚠️ {exc.message}"
        if isinstance(reply, CallbackQuery) and reply.message:
            await reply.message.answer(pe.premiumize(text))
        elif isinstance(reply, Message):
            await reply.answer(pe.premiumize(text))
        return True
    ok = pe.premiumize(texts.promo_ok(promo, amount))
    if isinstance(reply, CallbackQuery) and reply.message:
        await reply.message.answer(ok, reply_markup=keyboards.back_home())
    elif isinstance(reply, Message):
        await reply.answer(ok, reply_markup=keyboards.back_home())
    return True


async def _send_greeting(session: AsyncSession, reply: Message | CallbackQuery) -> None:
    greeting = await greetings.pick_greeting(session)
    if greeting is None:
        return
    markup = keyboards.greeting_keyboard(greeting.button_text, greeting.button_url)
    target = reply if isinstance(reply, Message) else reply.message
    if target is None:
        return
    try:
        await target.answer(greeting.body, reply_markup=markup)
    except TelegramBadRequest:
        return


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
    payload = ""
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            payload = parts[1]
    await state.clear()
    promo_code = promo_service.parse_promo_payload(payload)
    if promo_code:
        await state.update_data(pending_promo=promo_code)

    first_start = users.mark_started(db_user)
    await referrals.attach_referrer(
        session, user=db_user, payload=payload, settings=settings, first_start=first_start
    )
    campaign = campaigns.parse_campaign_payload(payload)
    if campaign:
        await campaigns.record_hit(
            session, code=campaign, user_id=db_user.id, is_new=first_start
        )
    if db_user.is_banned:
        await message.answer(
            pe.premiumize(texts.banned(db_user.ban_reason or "бан", settings.support_contact))
        )
        return
    if not is_admin:
        kind, text, markup, _result = await _gate_op(
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
    # Redeem before bump_activity: bump stamps claim cooldown and would make
    # promo.redeem raise «Слишком часто» on the same /start promo_ deep-link.
    await _try_redeem_pending_promo(
        session=session, user=db_user, settings=settings, state=state, reply=message
    )
    await bump_activity(session, db_user, 1)
    await referrals.activate_if_ready(session, user=db_user, settings=settings)
    text, markup = await render_home(
        session, db_user, bot_username=bot_username, is_admin=is_admin, settings=settings
    )
    await message.answer(pe.premiumize(text) if text else text, reply_markup=markup)
    await _send_greeting(session, message)
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
    state: FSMContext,
    bot_username: str,
    is_admin: bool,
) -> None:
    if db_user.is_banned:
        await safe_answer(call, texts.banned_short(), alert=True)
        return
    chat_id = call.message.chat.id if call.message else db_user.id
    kind, text, markup, _result = await _gate_op(
        user=db_user,
        settings=settings,
        session=session,
        bot=bot,
        chat_id=chat_id,
        op_gate=op_gate,
        verify=True,
    )
    if kind != "ok":
        alert = "Ещё не все подписки засчитаны" if kind == "op" else "Доступ ограничен"
        await safe_answer(call, alert, alert=True)
        await safe_edit(call.message, text, markup)
        return
    db_user.last_op_ok_at = datetime.now(UTC)
    await safe_answer(call, "Доступ открыт")
    await _try_redeem_pending_promo(
        session=session, user=db_user, settings=settings, state=state, reply=call
    )
    await bump_activity(session, db_user, 1)
    await referrals.activate_if_ready(session, user=db_user, settings=settings)
    home_text, home_markup = await render_home(
        session, db_user, bot_username=bot_username, is_admin=is_admin, settings=settings
    )
    await safe_edit(call.message, home_text, home_markup)
    await _send_greeting(session, call)
