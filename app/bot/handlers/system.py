"""Service handlers: bot block tracking and fallbacks. Registered last."""

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.admin.texts import no_access
from app.bot.utils import safe_answer
from app.services import users

router = Router(name="system")


@router.my_chat_member()
async def my_chat_member(event: ChatMemberUpdated, session: AsyncSession) -> None:
    if event.chat.type != ChatType.PRIVATE:
        return
    status = event.new_chat_member.status
    blocked = status in {ChatMemberStatus.KICKED, ChatMemberStatus.LEFT}
    await users.set_blocked_bot(session, event.chat.id, blocked)


@router.callback_query(F.data.startswith("admin:"))
async def admin_no_access(call: CallbackQuery) -> None:
    await safe_answer(call, no_access(), alert=True)


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery) -> None:
    await safe_answer(call)


@router.message(F.chat.type == ChatType.PRIVATE, F.text)
async def fallback_text(message: Message) -> None:
    await message.answer(texts.unknown_message())
