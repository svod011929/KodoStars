from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import BoostKind, BoostProduct, LedgerKind, User
from app.services import ledger, referrals
from app.services.antifraud import bump_activity
from app.services.boosts import grant_purchase
from app.services.levels import add_xp
from app.services.tasks import try_complete_event


async def fulfill_boost_payment(
    session: AsyncSession,
    *,
    user: User,
    product: BoostProduct,
    telegram_charge_id: str,
    settings: Settings,
) -> None:
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
            reference=f"boost:{product.slug}",
            extra={"charge_id": telegram_charge_id, "xtr": product.xtr_price},
        )
        await referrals.share_earning(
            session,
            earner=user,
            base_amount=product.stars_amount,
            settings=settings,
            source=f"boost:{product.slug}",
        )
    await add_xp(session, user, 15)
    await bump_activity(session, user, 2)
    await referrals.activate_if_ready(session, user=user, settings=settings)
    await try_complete_event(
        session, user=user, event="boost_purchased", settings=settings
    )
    await try_complete_event(
        session, user=user, event="invite_activated", settings=settings
    )
