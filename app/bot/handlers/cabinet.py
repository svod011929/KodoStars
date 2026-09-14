from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.render import render_home
from app.config import Settings
from app.db.models import User
from app.services import ledger, referrals
from app.services.levels import info_for_xp

router = Router(name="cabinet")


@router.callback_query(F.data == "menu:home")
async def menu_home(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
    bot: Bot,
) -> None:
    me = await bot.get_me()
    text, markup = await render_home(session, db_user, settings, me.username or "bot")
    await call.answer()
    if call.message:
        await call.message.edit_text(text, reply_markup=markup)


@router.callback_query(F.data == "menu:profile")
async def menu_profile(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
) -> None:
    balance = await ledger.get_balance(session, db_user.id)
    refs = await referrals.referral_stats(session, db_user.id)
    await call.answer()
    if call.message:
        await call.message.edit_text(
            texts.profile(db_user, balance, info_for_xp(db_user.xp), refs),
            reply_markup=keyboards.back_home(),
        )


@router.callback_query(F.data == "menu:refs")
async def menu_refs(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
    bot: Bot,
) -> None:
    me = await bot.get_me()
    stats = await referrals.referral_stats(session, db_user.id)
    await call.answer()
    if call.message:
        await call.message.edit_text(
            texts.referrals(
                db_user,
                me.username or "bot",
                stats,
                settings.min_referral_activity,
            ),
            reply_markup=keyboards.back_home(),
        )
