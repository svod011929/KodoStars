from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BoostKind, BoostProduct, User, UserBoost


async def list_products(session: AsyncSession) -> list[BoostProduct]:
    result = await session.execute(
        select(BoostProduct).where(BoostProduct.is_active.is_(True)).order_by(BoostProduct.xtr_price)
    )
    return list(result.scalars().all())


async def get_product(session: AsyncSession, product_id: int) -> BoostProduct | None:
    return await session.get(BoostProduct, product_id)


async def active_multiplier_bp(session: AsyncSession, user_id: int) -> int:
    now = datetime.now(UTC)
    result = await session.execute(
        select(UserBoost).where(
            UserBoost.user_id == user_id,
            UserBoost.expires_at.is_not(None),
            UserBoost.expires_at > now,
        )
    )
    best = 100
    for boost in result.scalars().all():
        best = max(best, boost.multiplier_bp)
    return best


async def grant_purchase(
    session: AsyncSession,
    *,
    user: User,
    product: BoostProduct,
    telegram_charge_id: str,
) -> UserBoost:
    existing = await session.execute(
        select(UserBoost).where(UserBoost.telegram_charge_id == telegram_charge_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("duplicate telegram charge")

    expires_at = None
    if product.kind == BoostKind.MULTIPLIER.value and product.duration_hours > 0:
        expires_at = datetime.now(UTC) + timedelta(hours=product.duration_hours)

    boost = UserBoost(
        user_id=user.id,
        product_id=product.id,
        multiplier_bp=product.multiplier_bp,
        expires_at=expires_at,
        telegram_charge_id=telegram_charge_id,
    )
    session.add(boost)
    await session.flush()
    return boost
