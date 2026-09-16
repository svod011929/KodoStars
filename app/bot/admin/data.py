from datetime import UTC, datetime
from io import BytesIO

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import safe_answer, safe_edit
from app.services import audit, export
from app.services.user_import import import_users_from_csv

router = Router(name="admin.data")

EXPORTS = {
    "users": ("users", export.users_csv),
    "wd": ("withdrawals", export.withdrawals_csv),
    "ledger": ("ledger", export.ledger_csv),
    "pay": ("payments", export.payments_csv),
}


@router.callback_query(F.data == "admin:data")
async def data_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(call)
    await safe_edit(call.message, texts.data_home(), kb.data_home())


@router.callback_query(F.data.startswith("admin:exp:"))
async def data_export(call: CallbackQuery, session: AsyncSession) -> None:
    key = (call.data or "").split(":")[-1]
    entry = EXPORTS.get(key)
    if entry is None or call.message is None:
        await safe_answer(call, "Неизвестный экспорт", alert=True)
        return
    name, builder = entry
    await safe_answer(call, "Готовлю файл…")
    payload = await builder(session)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    await call.message.answer_document(
        BufferedInputFile(payload, filename=f"kodostars_{name}_{stamp}.csv"),
        caption=f"Экспорт: {name}",
    )
    await audit.log_action(
        session, admin_id=call.from_user.id, action="export", target_type="dataset", target_id=name
    )


@router.callback_query(F.data == "admin:import")
async def import_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.import_users)
    await safe_answer(call)
    await safe_edit(call.message, texts.import_prompt(), kb.cancel_to("admin:data"))


@router.message(StateFilter(AdminFSM.import_users), F.document)
async def import_file(message: Message, session: AsyncSession, state: FSMContext) -> None:
    document = message.document
    if document is None or not (document.file_name or "").lower().endswith(".csv"):
        await message.answer(texts.import_need_csv())
        return
    buffer = BytesIO()
    await message.bot.download(document, destination=buffer)
    result = await import_users_from_csv(session, buffer.getvalue())
    await audit.log_action(
        session,
        admin_id=message.from_user.id,
        action="users.import",
        created=result.created,
        updated=result.updated,
        errors=result.errors,
    )
    await state.clear()
    await message.answer(
        texts.import_result(
            result.created, result.updated, result.unchanged, result.errors, result.error_lines
        ),
        reply_markup=kb.data_home(),
    )


@router.message(StateFilter(AdminFSM.import_users))
async def import_need_file(message: Message) -> None:
    await message.answer(texts.import_need_csv())
