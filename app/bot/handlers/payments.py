from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery, SuccessfulPayment
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.services.boosts import get_product
from app.services.economy import fulfill_boost_payment

router = Router(name="payments")


@router.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery,
    session: AsyncSession,
    db_user: User,
) -> None:
    if db_user.is_banned:
        await query.answer(ok=False, error_message="Аккаунт заблокирован")
        return
    payload = query.invoice_payload or ""
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "boost":
        await query.answer(ok=False, error_message="Некорректный платёж")
        return
    product = await get_product(session, int(parts[1]))
    if product is None or not product.is_active:
        await query.answer(ok=False, error_message="Буст больше недоступен")
        return
    if query.currency != "XTR" or query.total_amount != product.xtr_price:
        await query.answer(ok=False, error_message="Сумма не совпадает")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(
    message: Message,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    payment: SuccessfulPayment | None = message.successful_payment
    if payment is None:
        return
    parts = (payment.invoice_payload or "").split(":")
    if len(parts) != 3:
        return
    product = await get_product(session, int(parts[1]))
    if product is None:
        return
    await fulfill_boost_payment(
        session,
        user=db_user,
        product=product,
        telegram_charge_id=payment.telegram_payment_charge_id,
        settings=settings,
    )
    await message.answer(
        f"Оплата прошла. {product.title} активирован.\n"
        f"Чек Telegram: <code>{payment.telegram_payment_charge_id}</code>"
    )
