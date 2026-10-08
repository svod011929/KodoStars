"""Slash commands. Registered before FSM routers so a command always wins over
a pending text prompt (e.g. admin user search)."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.handlers.cabinet import profile_view, referrals_view, top_view
from app.bot.handlers.earn import daily_view
from app.bot.render import render_home
from app.config import Settings
from app.db.models import User
from app.services import ambassadors

router = Router(name="commands")


@router.message(Command("menu"))
async def cmd_menu(
    message: Message,
    session: AsyncSession,
    db_user: User,
    state: FSMContext,
    bot_username: str,
    is_admin: bool,
    settings: Settings,
) -> None:
    await state.clear()
    text, markup = await render_home(
        session, db_user, bot_username=bot_username, is_admin=is_admin, settings=settings
    )
    await message.answer(text, reply_markup=markup)


@router.message(Command("profile"))
async def cmd_profile(
    message: Message, session: AsyncSession, db_user: User, state: FSMContext, settings: Settings
) -> None:
    await state.clear()
    text, markup = await profile_view(session, db_user, settings)
    await message.answer(text, reply_markup=markup)


@router.message(Command("daily"))
async def cmd_daily(
    message: Message, session: AsyncSession, db_user: User, state: FSMContext, settings: Settings
) -> None:
    await state.clear()
    text, markup = await daily_view(session, db_user, settings)
    await message.answer(text, reply_markup=markup)


@router.message(Command("ref", "invite"))
async def cmd_ref(
    message: Message,
    session: AsyncSession,
    db_user: User,
    state: FSMContext,
    settings: Settings,
    bot_username: str,
) -> None:
    await state.clear()
    text, markup = await referrals_view(session, db_user, settings, bot_username)
    await message.answer(text, reply_markup=markup)


@router.message(Command("top"))
async def cmd_top(
    message: Message, session: AsyncSession, db_user: User, state: FSMContext, settings: Settings
) -> None:
    await state.clear()
    text, markup = await top_view(session, db_user, settings, "contest")
    await message.answer(text, reply_markup=markup)


@router.message(Command("help"))
async def cmd_help(
    message: Message,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
    is_admin: bool,
    state: FSMContext,
) -> None:
    await state.clear()
    terms = await ambassadors.effective_referral_terms(session, db_user.id, settings)
    await message.answer(
        texts.help_text(settings, is_admin, terms=terms),
        reply_markup=keyboards.help_menu(settings.support_contact),
    )


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        texts.paysupport(settings), reply_markup=keyboards.help_menu(settings.support_contact)
    )


@router.message(Command("terms"))
async def cmd_terms(message: Message, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.terms(settings), reply_markup=keyboards.back_home())
