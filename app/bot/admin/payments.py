from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.utils import PAGE_SIZE, parse_id, safe_answer, safe_edit
from app.db.models import BoostProduct, User
from app.services import audit
from app.services import payments as payment_service
from app.services.errors import EconomyError

router = Router(name="admin.payments")


async def _titles(session: AsyncSession, items) -> dict[int, str]:
    titles: dict[int, str] = {}
    for item in items:
        if item.product_id and item.product_id not in titles:
            product = await session.get(BoostProduct, item.product_id)
            titles[item.product_id] = product.title if product else "—"
    return titles


@router.callback_query(F.data.regexp(r"^admin:pay:(\d+)$"))
async def payments_home(call: CallbackQuery, session: AsyncSession) -> None:
    page = parse_id(call.data)
    total = await payment_service.count_payments(session)
    items = await payment_service.list_payments(session, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    revenue = await payment_service.revenue_xtr(session)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.payments_home(items, await _titles(session, items), page, total, PAGE_SIZE, revenue),
        kb.payments_home(items, page, total),
    )


@router.callback_query(F.data.regexp(r"^admin:pay:view:(\d+)$"))
async def payment_view(call: CallbackQuery, session: AsyncSession) -> None:
    try:
        payment = await payment_service.get_payment(session, parse_id(call.data))
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    title = (await _titles(session, [payment])).get(payment.product_id or 0, "—")
    user = await session.get(User, payment.user_id)
    await safe_answer(call)
    await safe_edit(call.message, texts.payment_card(payment, title, user), kb.payment_card(payment))


@router.callback_query(F.data.regexp(r"^admin:pay:refund:(\d+)$"))
async def payment_refund_ask(call: CallbackQuery, session: AsyncSession) -> None:
    try:
        payment = await payment_service.get_payment(session, parse_id(call.data))
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    title = (await _titles(session, [payment])).get(payment.product_id or 0, "—")
    await safe_answer(call)
    await safe_edit(call.message, texts.refund_confirm(payment, title), kb.refund_confirm(payment.id))


@router.callback_query(F.data.regexp(r"^admin:pay:refund:(\d+):yes$"))
async def payment_refund(call: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    try:
        payment = await payment_service.get_payment(session, parse_id(call.data, -2))
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return

    async def _refund_call(user_id: int, charge_id: str) -> bool:
        try:
            return bool(await bot.refund_star_payment(user_id=user_id, telegram_payment_charge_id=charge_id))
        except TelegramAPIError:
            return False

    try:
        await payment_service.refund(
            session, payment=payment, admin_id=call.from_user.id, refund_call=_refund_call
        )
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="payment.refund",
        target_type="payment",
        target_id=payment.id,
        xtr=payment.xtr_amount,
    )
    title = (await _titles(session, [payment])).get(payment.product_id or 0, "—")
    user = await session.get(User, payment.user_id)
    await safe_answer(call, "Возврат выполнен", alert=True)
    await safe_edit(call.message, texts.payment_card(payment, title, user), kb.payment_card(payment))
