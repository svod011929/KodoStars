from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import BoostKind, BoostProduct, LedgerKind, User
from app.services import ledger, payments, referrals
from app.services.antifraud import bump_activity
from app.services.boosts import grant_purchase
from app.services.levels import XP_BOOST, add_xp
from app.services.tasks import try_complete_event


async def fulfill_boost_payment(
    session: AsyncSession,
    *,
    user: User,
    product: BoostProduct,
    telegram_charge_id: str,
    settings: Settings,
    provider_charge_id: str | None = None,
    invoice_payload: str | None = None,
    xtr_amount: int | None = None,
) -> bool:
    """Grant the purchase. Returns False when this charge was already fulfilled.

    Telegram may redeliver ``successful_payment`` after a restart; the payment
    record makes the whole operation idempotent.
    """
    _, created = await payments.record_payment(
        session,
        user=user,
        product=product,
        telegram_charge_id=telegram_charge_id,
        provider_charge_id=provider_charge_id,
        invoice_payload=invoice_payload,
        xtr_amount=xtr_amount if xtr_amount is not None else product.xtr_price,
    )
    if not created:
        return False

    await grant_purchase(
        session,
        user=user,
        product=product,
        telegram_charge_id=telegram_charge_id,
    )
    if product.kind == BoostKind.STARS_PACK.value and product.stars_amount > 0:
        await ledger.credit(
            session,
            user_id=user.id,
            amount=product.stars_amount,
            kind=LedgerKind.BOOST_PACK,
            reference=f"boost:{product.slug}"[:64],
            extra={"charge_id": telegram_charge_id, "xtr": product.xtr_price},
        )
        await referrals.share_earning(
            session,
            earner=user,
            base_amount=product.stars_amount,
            settings=settings,
            source=f"boost:{product.slug}",
        )
    await add_xp(session, user, XP_BOOST)
    await bump_activity(session, user, 2)
    await referrals.activate_if_ready(session, user=user, settings=settings)
    await try_complete_event(session, user=user, event="boost_purchased", settings=settings)
    if user.referred_by_id:
        referrer = await session.get(User, user.referred_by_id)
        if referrer is not None and not referrer.is_banned:
            await try_complete_event(session, user=referrer, event="invite_activated", settings=settings)
    return True
