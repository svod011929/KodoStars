import structlog
from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery, SuccessfulPayment
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.config import Settings
from app.db.models import User
from app.services.boosts import get_product
from app.services.economy import fulfill_boost_payment

log = structlog.get_logger("kodostars.payments")
router = Router(name="payments")


def _parse_payload(payload: str | None) -> int | None:
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != "boost" or not parts[1].isdigit():
        return None
    return int(parts[1])


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, session: AsyncSession, db_user: User) -> None:
    if db_user.is_banned:
        await query.answer(ok=False, error_message="Аккаунт заблокирован")
        return
    product_id = _parse_payload(query.invoice_payload)
    if product_id is None:
        await query.answer(ok=False, error_message="Некорректный платёж")
        return
    product = await get_product(session, product_id)
    if product is None or not product.is_active:
        await query.answer(ok=False, error_message="Буст больше недоступен")
        return
    if query.currency != "XTR" or query.total_amount != product.xtr_price:
        await query.answer(ok=False, error_message="Сумма не совпадает")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(
    message: Message, session: AsyncSession, db_user: User, settings: Settings
) -> None:
    payment: SuccessfulPayment | None = message.successful_payment
    if payment is None:
        return
    product_id = _parse_payload(payment.invoice_payload)
    product = await get_product(session, product_id) if product_id is not None else None
    if product is None:
        log.error(
            "payment_without_product",
            payload=payment.invoice_payload,
            charge=payment.telegram_payment_charge_id,
        )
        await message.answer("Оплата получена, но товар не найден. Напишите в /paysupport — мы разберёмся.")
        return
    created = await fulfill_boost_payment(
        session,
        user=db_user,
        product=product,
        telegram_charge_id=payment.telegram_payment_charge_id,
        settings=settings,
        provider_charge_id=payment.provider_payment_charge_id,
        invoice_payload=payment.invoice_payload,
        xtr_amount=payment.total_amount,
    )
    if not created:
        log.info("payment_duplicate_delivery", charge=payment.telegram_payment_charge_id)
        return
    await message.answer(
        texts.payment_done(product.title, payment.telegram_payment_charge_id),
        reply_markup=keyboards.back_home(),
    )
