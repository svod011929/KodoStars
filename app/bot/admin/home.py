from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.utils import PAGE_SIZE, parse_id, safe_answer, safe_edit
from app.config import Settings
from app.db.models import User
from app.services import antifraud, audit, devices, ledger, piarflow_quality, stats, withdrawals
from app.services.broadcasts import running_broadcast

router = Router(name="admin.home")


async def _home_view(session: AsyncSession, settings: Settings) -> tuple[str, object]:
    pending = await withdrawals.count_queue(session)
    running = await running_broadcast(session) is not None
    return texts.home(__version__, pending, running, settings.maintenance_mode), kb.home()


@router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _home_view(session, settings)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "admin:home")
async def admin_home(
    call: CallbackQuery, session: AsyncSession, settings: Settings, state: FSMContext
) -> None:
    await state.clear()
    text, markup = await _home_view(session, settings)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery) -> None:
    await safe_answer(call)


@router.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    data = await stats.dashboard(session)
    days = await stats.registrations_by_day(session, days=7)
    pf = await piarflow_quality.traffic_stats(session)
    star_balance: int | None = None
    try:
        amount = await bot.get_my_star_balance()
        star_balance = int(amount.amount)
    except (TelegramAPIError, AttributeError):
        star_balance = None
    await safe_answer(call)
    await safe_edit(call.message, texts.stats(data, star_balance, days, pf), kb.stats())


@router.callback_query(F.data == "admin:reconcile")
async def admin_reconcile(call: CallbackQuery, session: AsyncSession) -> None:
    rows = await ledger.reconcile(session)
    await safe_answer(call)
    await safe_edit(call.message, texts.reconcile(rows), kb.reconcile(bool(rows)))


@router.callback_query(F.data == "admin:reconcile:fix")
async def admin_reconcile_fix(call: CallbackQuery, session: AsyncSession) -> None:
    rows = await ledger.reconcile(session, limit=500)
    fixed = 0
    for uid, _balance, total in rows:
        user = await session.get(User, uid)
        if user is None:
            continue
        user.balance = total
        fixed += 1
    await session.flush()
    await audit.log_action(session, admin_id=call.from_user.id, action="ledger.reconcile", fixed=fixed)
    await safe_answer(call, f"Исправлено: {fixed}", alert=True)
    remaining = await ledger.reconcile(session)
    await safe_edit(call.message, texts.reconcile(remaining), kb.reconcile(bool(remaining)))


@router.callback_query(F.data.startswith("admin:audit:"))
async def admin_audit(call: CallbackQuery, session: AsyncSession) -> None:
    page = parse_id(call.data)
    total = await audit.count(session)
    items = await audit.recent(session, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    await safe_answer(call)
    await safe_edit(call.message, texts.audit(items, page, total, PAGE_SIZE), kb.audit(page, total))


@router.callback_query(F.data.startswith("admin:fraud:"))
async def admin_fraud(call: CallbackQuery, session: AsyncSession) -> None:
    page = parse_id(call.data)
    total = await antifraud.count_events(session)
    items = await antifraud.recent_events(session, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.fraud_events(items, page, total, PAGE_SIZE, None),
        kb.fraud(page, total, None),
    )


@router.callback_query(F.data == "admin:suspicious")
async def admin_suspicious(call: CallbackQuery, session: AsyncSession) -> None:
    rows = await antifraud.suspicious_referrers(session)
    await safe_answer(call)
    await safe_edit(call.message, texts.suspicious(rows), kb.suspicious(rows))


@router.callback_query(F.data == "admin:twinks")
async def admin_twinks(call: CallbackQuery, session: AsyncSession) -> None:
    clusters = await devices.clusters(session)
    summary = await devices.stats(session)
    await safe_answer(call)
    await safe_edit(call.message, texts.twinks_report(clusters, summary), kb.twinks(clusters))
