from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import markup, parse_id, safe_answer, safe_edit, url_button
from app.db.models import Broadcast, BroadcastAudience
from app.services import audit
from app.services import broadcasts as bc
from app.services.broadcasts import BroadcastRunner
from app.services.errors import EconomyError

router = Router(name="admin.broadcast")


def button_markup(text: str | None, url: str | None) -> InlineKeyboardMarkup | None:
    if text and url:
        return markup([url_button(text, url)])
    return None


@router.callback_query(F.data == "admin:bc")
async def bc_home(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    running = await bc.running_broadcast(session)
    history = await bc.list_broadcasts(session, limit=5)
    await safe_answer(call)
    await safe_edit(call.message, texts.broadcast_home(history, running), kb.broadcast_home(running, history))


@router.callback_query(F.data == "admin:bc:new")
async def bc_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.bc_message)
    await state.set_data({})
    await safe_answer(call)
    await safe_edit(call.message, texts.broadcast_prompt(), kb.cancel_to("admin:bc"))


@router.message(StateFilter(AdminFSM.bc_message))
async def bc_message(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    # Promo deep-link flow already filled button_text/url — skip the button step.
    if data.get("button_text") and data.get("button_url"):
        await _ask_audience(message, session, state)
        return
    await state.set_state(AdminFSM.bc_button)
    await message.answer(texts.broadcast_button_prompt(), reply_markup=kb.broadcast_button_step())


async def _ask_audience(message: Message, session: AsyncSession, state: FSMContext) -> None:
    sizes = {key.value: await bc.audience_size(session, key.value) for key in BroadcastAudience}
    await state.set_state(None)
    await message.answer(texts.broadcast_audience_prompt(sizes), reply_markup=kb.broadcast_audience())


@router.callback_query(F.data == "admin:bc:btn:no")
async def bc_button_skip(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not (await state.get_data()).get("message_id"):
        await safe_answer(call, "Сначала отправьте сообщение", alert=True)
        return
    await state.update_data(button_text=None, button_url=None)
    await safe_answer(call)
    if call.message:
        await _ask_audience(call.message, session, state)


@router.message(StateFilter(AdminFSM.bc_button), F.text)
async def bc_button_set(message: Message, session: AsyncSession, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if "|" not in raw:
        await message.answer(
            "Формат: <code>Текст | https://ссылка</code>", reply_markup=kb.broadcast_button_step()
        )
        return
    text, url = (part.strip() for part in raw.split("|", 1))
    if not text or not url.startswith(("http://", "https://", "tg://")):
        await message.answer("Ссылка должна начинаться с https://", reply_markup=kb.broadcast_button_step())
        return
    await state.update_data(button_text=text[:64], button_url=url[:512])
    await _ask_audience(message, session, state)


@router.callback_query(F.data.startswith("admin:bc:aud:"))
async def bc_audience(call: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    audience = (call.data or "").split(":")[-1]
    data = await state.get_data()
    if not data.get("message_id"):
        await safe_answer(call, "Сначала отправьте сообщение", alert=True)
        return
    await state.update_data(audience=audience)
    size = await bc.audience_size(session, audience)
    await safe_answer(call)
    if call.message is None:
        return
    try:
        await bot.copy_message(
            chat_id=call.message.chat.id,
            from_chat_id=data["from_chat_id"],
            message_id=data["message_id"],
            reply_markup=button_markup(data.get("button_text"), data.get("button_url")),
        )
    except TelegramAPIError as exc:
        await call.message.answer(f"Не удалось показать превью: {exc}")
    await call.message.answer(
        texts.broadcast_confirm(audience, size, data.get("button_text")),
        reply_markup=kb.broadcast_confirm(),
    )


@router.callback_query(F.data == "admin:bc:test")
async def bc_test(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if not data.get("message_id"):
        await safe_answer(call, "Черновик потерян, начните заново", alert=True)
        return
    try:
        await bot.copy_message(
            chat_id=call.from_user.id,
            from_chat_id=data["from_chat_id"],
            message_id=data["message_id"],
            reply_markup=button_markup(data.get("button_text"), data.get("button_url")),
        )
        await safe_answer(call, "Тестовое сообщение отправлено вам")
    except TelegramAPIError as exc:
        await safe_answer(call, f"Ошибка: {exc}"[:190], alert=True)


@router.callback_query(F.data == "admin:bc:go")
async def bc_go(
    call: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    broadcast_runner: BroadcastRunner,
) -> None:
    data = await state.get_data()
    if not data.get("message_id") or not data.get("audience"):
        await safe_answer(call, "Черновик потерян, начните заново", alert=True)
        return
    if await bc.running_broadcast(session) is not None:
        await safe_answer(call, "Дождитесь окончания текущей рассылки", alert=True)
        return
    try:
        row = await bc.create_broadcast(
            session,
            admin_id=call.from_user.id,
            from_chat_id=data["from_chat_id"],
            message_id=data["message_id"],
            audience=data["audience"],
            button_text=data.get("button_text"),
            button_url=data.get("button_url"),
        )
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="broadcast.start",
        target_type="broadcast",
        target_id=row.id,
        audience=row.audience,
        total=row.total,
    )
    await session.commit()
    await state.clear()
    broadcast_runner.start(row.id)
    await safe_answer(call, "Рассылка запущена")
    if call.message:
        progress = await call.message.answer(
            texts.broadcast_progress(row), reply_markup=kb.broadcast_progress(row, True)
        )
        broadcast_runner.watch(row.id, progress.chat.id, progress.message_id)


@router.callback_query(F.data.regexp(r"^admin:bc:view:(\d+)$"))
async def bc_view(call: CallbackQuery, session: AsyncSession, broadcast_runner: BroadcastRunner) -> None:
    row = await session.get(Broadcast, parse_id(call.data))
    if row is None:
        await safe_answer(call, "Не найдено", alert=True)
        return
    running = broadcast_runner.is_running(row.id)
    await safe_answer(call)
    await safe_edit(call.message, texts.broadcast_progress(row), kb.broadcast_progress(row, running))


@router.callback_query(F.data.regexp(r"^admin:bc:stop:(\d+)$"))
async def bc_stop(call: CallbackQuery, session: AsyncSession, broadcast_runner: BroadcastRunner) -> None:
    broadcast_id = parse_id(call.data)
    if broadcast_runner.cancel(broadcast_id):
        await audit.log_action(
            session,
            admin_id=call.from_user.id,
            action="broadcast.cancel",
            target_type="broadcast",
            target_id=broadcast_id,
        )
        await safe_answer(call, "Останавливаю…")
    else:
        await safe_answer(call, "Рассылка уже не выполняется", alert=True)
    row = await session.get(Broadcast, broadcast_id)
    if row is not None:
        await safe_edit(call.message, texts.broadcast_progress(row), kb.broadcast_progress(row, False))


@router.message(StateFilter(AdminFSM.bc_button))
async def bc_button_other(message: Message) -> None:
    await message.answer(texts.broadcast_button_prompt(), reply_markup=kb.broadcast_button_step())
