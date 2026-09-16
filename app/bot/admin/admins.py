import contextlib

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommandScopeChat, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.commands import ADMIN_COMMANDS, USER_COMMANDS
from app.bot.utils import parse_id, safe_answer, safe_edit
from app.db.models import User
from app.services import audit
from app.services.access import AccessRegistry
from app.services.errors import EconomyError

router = Router(name="admin.admins")


async def _view(session: AsyncSession, access: AccessRegistry, viewer_id: int):
    rows = await access.list_admins(session)
    names: dict[int, str] = {}
    for uid in [*access.owners, *[row.user_id for row in rows]]:
        user = await session.get(User, uid)
        names[uid] = user.display_name if user else ""
    return texts.admins_home(sorted(access.owners), rows, names), kb.admins(rows, access.is_owner(viewer_id))


@router.callback_query(F.data == "admin:adm")
async def admins_home(
    call: CallbackQuery, session: AsyncSession, state: FSMContext, access: AccessRegistry
) -> None:
    await state.clear()
    text, markup = await _view(session, access, call.from_user.id)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "admin:adm:add")
async def admin_add_start(call: CallbackQuery, state: FSMContext, access: AccessRegistry) -> None:
    if not access.is_owner(call.from_user.id):
        await safe_answer(call, texts.no_access(), alert=True)
        return
    await state.set_state(AdminFSM.admin_add)
    await safe_answer(call)
    await safe_edit(call.message, texts.admin_add_prompt(), kb.cancel_to("admin:adm"))


@router.message(StateFilter(AdminFSM.admin_add), F.text)
async def admin_add(
    message: Message, session: AsyncSession, state: FSMContext, access: AccessRegistry, bot: Bot
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой Telegram ID.")
        return
    user_id = int(raw)
    if await session.get(User, user_id) is None:
        await message.answer("Пользователь ещё не запускал бота — сначала попросите его нажать /start.")
        return
    try:
        await access.add_admin(session, user_id=user_id, actor_id=message.from_user.id)
    except EconomyError as exc:
        await message.answer(exc.message)
        return
    await audit.log_action(
        session, admin_id=message.from_user.id, action="admin.add", target_type="user", target_id=user_id
    )
    await _set_commands(bot, user_id, admin=True)
    await state.clear()
    text, markup = await _view(session, access, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^admin:adm:del:(\d+)$"))
async def admin_remove(call: CallbackQuery, session: AsyncSession, access: AccessRegistry, bot: Bot) -> None:
    user_id = parse_id(call.data)
    try:
        await access.remove_admin(session, user_id=user_id, actor_id=call.from_user.id)
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session, admin_id=call.from_user.id, action="admin.remove", target_type="user", target_id=user_id
    )
    await _set_commands(bot, user_id, admin=False)
    text, markup = await _view(session, access, call.from_user.id)
    await safe_answer(call, "Удалён")
    await safe_edit(call.message, text, markup)


async def _set_commands(bot: Bot, user_id: int, *, admin: bool) -> None:
    with contextlib.suppress(TelegramAPIError):
        await bot.set_my_commands(
            ADMIN_COMMANDS if admin else USER_COMMANDS, scope=BotCommandScopeChat(chat_id=user_id)
        )
