from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.config import Settings
from app.db.models import User, Withdrawal
from app.op.gate import CASCADE, enabled_providers, toggle_provider
from app.services import stats, users, withdrawals
from app.services.antifraud import set_ban
from app.services.errors import WithdrawalError

router = Router(name="admin")


class AdminFSM(StatesGroup):
    broadcast = State()
    ban_id = State()
    ban_reason = State()
    unban_id = State()


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message, settings: Settings) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    await message.answer(texts.admin_home(), reply_markup=keyboards.admin_home())


@router.callback_query(F.data == "admin:home")
async def admin_home(call: CallbackQuery, settings: Settings) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    await call.answer()
    if call.message:
        await call.message.edit_text(texts.admin_home(), reply_markup=keyboards.admin_home())


@router.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    data = await stats.dashboard(session)
    await call.answer()
    if call.message:
        await call.message.edit_text(texts.admin_stats(data), reply_markup=keyboards.admin_home())


@router.callback_query(F.data == "admin:wd")
async def admin_wd_queue(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    queue = await withdrawals.list_queue(session)
    await call.answer()
    if call.message:
        if not queue:
            await call.message.edit_text("Очередь выводов пуста.", reply_markup=keyboards.admin_home())
            return
        await call.message.edit_text(
            "Очередь выводов (pending + approved_manual):",
            reply_markup=keyboards.admin_wd_list(queue),
        )


@router.callback_query(F.data.startswith("admin:wd:view:"))
async def admin_wd_view(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    wd_id = int((call.data or "0").split(":")[-1])
    wd = await session.get(Withdrawal, wd_id)
    if wd is None:
        await call.answer("Не найдено", show_alert=True)
        return
    user = await session.get(User, wd.user_id)
    await call.answer()
    if call.message:
        await call.message.edit_text(
            texts.admin_wd(wd, user.username if user else None),
            reply_markup=keyboards.admin_wd_view(wd.id),
        )


@router.callback_query(F.data.startswith("admin:wd:ok:"))
async def admin_wd_ok(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    wd = await session.get(Withdrawal, int((call.data or "0").split(":")[-1]))
    if wd is None:
        await call.answer("Не найдено", show_alert=True)
        return
    try:
        await withdrawals.approve_manual(session, withdrawal=wd, admin_id=call.from_user.id)
    except WithdrawalError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("Согласовано — ждёт ручной отправки Stars")
    if call.message:
        await call.message.edit_text(
            texts.admin_wd(wd, None),
            reply_markup=keyboards.admin_wd_view(wd.id),
        )


@router.callback_query(F.data.startswith("admin:wd:no:"))
async def admin_wd_no(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    wd = await session.get(Withdrawal, int((call.data or "0").split(":")[-1]))
    if wd is None:
        await call.answer("Не найдено", show_alert=True)
        return
    try:
        await withdrawals.reject(
            session, withdrawal=wd, admin_id=call.from_user.id, note="Отклонено администратором"
        )
    except WithdrawalError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("Отклонено")
    if call.message:
        await call.message.edit_text("Заявка отклонена.", reply_markup=keyboards.admin_home())


@router.callback_query(F.data.startswith("admin:wd:sent:"))
async def admin_wd_sent(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    wd = await session.get(Withdrawal, int((call.data or "0").split(":")[-1]))
    if wd is None:
        await call.answer("Не найдено", show_alert=True)
        return
    try:
        await withdrawals.confirm_sent(session, withdrawal=wd, admin_id=call.from_user.id)
    except WithdrawalError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("Списано с леджера, статус sent")
    if call.message:
        await call.message.edit_text(
            f"Вывод #{wd.id} отмечен как отправленный. Леджер обновлён.",
            reply_markup=keyboards.admin_home(),
        )


@router.callback_query(F.data == "admin:prov")
async def admin_prov(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    enabled = await enabled_providers(session, settings)
    states = {name: name in enabled for name in CASCADE}
    await call.answer()
    if call.message:
        await call.message.edit_text(
            "Каскад OP: Flyer → SubGram → BotoHub → PiarFlow → TGrass → manual.\n"
            "Выключенный провайдер пропускается. Ошибки API — fail-open.",
            reply_markup=keyboards.admin_providers(states),
        )


@router.callback_query(F.data.startswith("admin:prov:tg:"))
async def admin_prov_toggle(
    call: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    name = (call.data or "").split(":")[-1]
    row = await toggle_provider(session, name, admin_id=call.from_user.id)
    if row is None:
        await call.answer("Неизвестный провайдер", show_alert=True)
        return
    enabled = await enabled_providers(session, settings)
    states = {item: item in enabled for item in CASCADE}
    await call.answer(f"{name}: {'ON' if row.enabled else 'OFF'}")
    if call.message:
        await call.message.edit_reply_markup(reply_markup=keyboards.admin_providers(states))


@router.callback_query(F.data == "admin:bc")
async def admin_bc_start(
    call: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    await state.set_state(AdminFSM.broadcast)
    await call.answer()
    if call.message:
        await call.message.edit_text(
            "Пришлите текст рассылки следующим сообщением. HTML разрешён.",
            reply_markup=keyboards.admin_home(),
        )


@router.message(StateFilter(AdminFSM.broadcast))
async def admin_bc_send(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    settings: Settings,
) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    await state.clear()
    ids = await users.list_user_ids(session)
    sent = 0
    failed = 0
    for user_id in ids:
        try:
            await message.bot.send_message(user_id, message.html_text or message.text or "")
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"Рассылка: отправлено {sent}, ошибок {failed}.")


@router.callback_query(F.data == "admin:ban")
async def admin_ban_start(
    call: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    await state.set_state(AdminFSM.ban_id)
    await call.answer()
    if call.message:
        await call.message.edit_text("Пришлите Telegram ID пользователя для бана.")


@router.message(StateFilter(AdminFSM.ban_id))
async def admin_ban_id(message: Message, state: FSMContext, settings: Settings) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой Telegram ID.")
        return
    await state.update_data(ban_id=int(raw))
    await state.set_state(AdminFSM.ban_reason)
    await message.answer("Причина бана:")


@router.message(StateFilter(AdminFSM.ban_reason))
async def admin_ban_reason(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    settings: Settings,
) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    data = await state.get_data()
    await state.clear()
    user = await session.get(User, int(data["ban_id"]))
    if user is None:
        await message.answer("Пользователь не найден.")
        return
    await set_ban(
        session,
        user,
        banned=True,
        reason=message.text or "ban",
        admin_id=message.from_user.id,
    )
    await message.answer(f"Пользователь {user.id} заблокирован.")


@router.callback_query(F.data == "admin:unban")
async def admin_unban_start(
    call: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    if not _is_admin(call.from_user.id, settings):
        await call.answer()
        return
    await state.set_state(AdminFSM.unban_id)
    await call.answer()
    if call.message:
        await call.message.edit_text("Пришлите Telegram ID для разбана.")


@router.message(StateFilter(AdminFSM.unban_id))
async def admin_unban(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    settings: Settings,
) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    await state.clear()
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой Telegram ID.")
        return
    user = await session.get(User, int(raw))
    if user is None:
        await message.answer("Пользователь не найден.")
        return
    await set_ban(session, user, banned=False, reason="", admin_id=message.from_user.id)
    await message.answer(f"Пользователь {user.id} разблокирован.")
