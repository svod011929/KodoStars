"""Telegram Stars payment records and refunds."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BoostKind, BoostProduct, LedgerKind, Payment, PaymentStatus, User
from app.services import events, ledger
from app.services.boosts import revoke_by_charge
from app.services.errors import NotFound, ValidationError

RefundCall = Callable[[int, str], Awaitable[bool]]


async def get_by_charge(session: AsyncSession, telegram_charge_id: str) -> Payment | None:
    result = await session.execute(select(Payment).where(Payment.telegram_charge_id == telegram_charge_id))
    return result.scalar_one_or_none()


async def record_payment(
    session: AsyncSession,
    *,
    user: User,
    product: BoostProduct | None,
    telegram_charge_id: str,
    provider_charge_id: str | None,
    invoice_payload: str | None,
    xtr_amount: int,
) -> tuple[Payment, bool]:
    existing = await get_by_charge(session, telegram_charge_id)
    if existing is not None:
        return existing, False
    payment = Payment(
        user_id=user.id,
        product_id=product.id if product else None,
        telegram_charge_id=telegram_charge_id,
        provider_charge_id=provider_charge_id,
        invoice_payload=(invoice_payload or "")[:128] or None,
        xtr_amount=xtr_amount,
        status=PaymentStatus.PAID.value,
    )
    session.add(payment)
    await session.flush()
    return payment, True


async def list_payments(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[Payment]:
    stmt = select(Payment).order_by(Payment.id.desc()).offset(offset).limit(limit)
    if user_id is not None:
        stmt = stmt.where(Payment.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_payments(session: AsyncSession, *, user_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(Payment)
    if user_id is not None:
        stmt = stmt.where(Payment.user_id == user_id)
    return int((await session.execute(stmt)).scalar_one())


async def revenue_xtr(session: AsyncSession, *, since: datetime | None = None) -> int:
    stmt = select(func.coalesce(func.sum(Payment.xtr_amount), 0)).where(
        Payment.status == PaymentStatus.PAID.value
    )
    if since is not None:
        stmt = stmt.where(Payment.created_at >= since)
    return int((await session.execute(stmt)).scalar_one())


async def refund(
    session: AsyncSession,
    *,
    payment: Payment,
    admin_id: int,
    refund_call: RefundCall,
) -> Payment:
    """Refund through Telegram, then revoke what the purchase granted.

    * ``stars_pack`` → the credited Stars are debited back (balance may go negative
      if the user already withdrew them; admins see that in the card).
    * ``multiplier`` → the boost expires immediately.
    """
    if payment.status == PaymentStatus.REFUNDED.value:
        raise ValidationError("Платёж уже возвращён")
    ok = await refund_call(payment.user_id, payment.telegram_charge_id)
    if not ok:
        raise ValidationError("Telegram отклонил возврат. Проверьте срок и статус платежа.")

    payment.status = PaymentStatus.REFUNDED.value
    payment.refunded_at = datetime.now(UTC)
    payment.refunded_by = admin_id

    product = await session.get(BoostProduct, payment.product_id) if payment.product_id else None
    revoked_stars = 0
    if product is not None and product.kind == BoostKind.STARS_PACK.value and product.stars_amount > 0:
        await ledger.debit(
            session,
            user_id=payment.user_id,
            amount=product.stars_amount,
            kind=LedgerKind.REFUND_REVOKE,
            reference=f"refund:{payment.id}",
            extra={"charge_id": payment.telegram_charge_id, "admin_id": admin_id},
            allow_negative=True,
        )
        revoked_stars = product.stars_amount
    await revoke_by_charge(session, payment.telegram_charge_id)
    await session.flush()
    events.emit(
        session,
        "payment_refunded",
        user_id=payment.user_id,
        xtr_amount=payment.xtr_amount,
        revoked_stars=revoked_stars,
        product_title=product.title if product else "",
    )
    return payment


async def get_payment(session: AsyncSession, payment_id: int) -> Payment:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise NotFound("Платёж не найден")
    return payment
