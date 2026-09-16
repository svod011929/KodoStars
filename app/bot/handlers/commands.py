"""Slash commands. Registered before FSM routers so a command always wins over
a pending text prompt (e.g. admin user search)."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.handlers.cabinet import profile_view
from app.bot.render import render_home
from app.config import Settings
from app.db.models import User

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
async def cmd_profile(message: Message, session: AsyncSession, db_user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await profile_view(session, db_user)
    await message.answer(text, reply_markup=markup)


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings, is_admin: bool, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        texts.help_text(settings, is_admin), reply_markup=keyboards.help_menu(settings.support_contact)
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
