import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BoostKind, BoostProduct, User, UserBoost
from app.services.errors import NotFound, ValidationError

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, prefix: str = "") -> str:
    base = _SLUG_RE.sub("_", value.lower()).strip("_") or "item"
    return f"{prefix}{base}"[:56]


def describe(product: BoostProduct) -> str:
    """Short human-readable description of what the product grants."""
    if product.kind == BoostKind.STARS_PACK.value:
        return f"пак {product.stars_amount} ⭐"
    multiplier = f"{product.multiplier_bp / 100:.2f}".rstrip("0").rstrip(".")
    return f"×{multiplier} на {product.duration_hours} ч"


async def list_products(session: AsyncSession) -> list[BoostProduct]:
    result = await session.execute(
        select(BoostProduct).where(BoostProduct.is_active.is_(True)).order_by(BoostProduct.xtr_price)
    )
    return list(result.scalars().all())


async def list_all_products(session: AsyncSession) -> list[BoostProduct]:
    result = await session.execute(select(BoostProduct).order_by(BoostProduct.xtr_price, BoostProduct.id))
    return list(result.scalars().all())


async def get_product(session: AsyncSession, product_id: int) -> BoostProduct | None:
    return await session.get(BoostProduct, product_id)


async def active_boosts(session: AsyncSession, user_id: int) -> list[UserBoost]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(UserBoost)
        .where(
            UserBoost.user_id == user_id,
            UserBoost.expires_at.is_not(None),
            UserBoost.expires_at > now,
        )
        .order_by(UserBoost.expires_at.desc())
    )
    return list(result.scalars().all())


async def active_multiplier_bp(session: AsyncSession, user_id: int) -> int:
    best = 100
    for boost in await active_boosts(session, user_id):
        best = max(best, boost.multiplier_bp)
    return best


async def grant_purchase(
    session: AsyncSession,
    *,
    user: User,
    product: BoostProduct,
    telegram_charge_id: str,
) -> tuple[UserBoost, bool]:
    """Create the entitlement. Idempotent per ``telegram_charge_id``: returns ``(row, created)``."""
    existing = await session.execute(
        select(UserBoost).where(UserBoost.telegram_charge_id == telegram_charge_id)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row, False

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
    return boost, True


async def revoke_by_charge(session: AsyncSession, telegram_charge_id: str) -> UserBoost | None:
    """Expire a multiplier immediately (used on refunds)."""
    result = await session.execute(
        select(UserBoost).where(UserBoost.telegram_charge_id == telegram_charge_id)
    )
    boost = result.scalar_one_or_none()
    if boost is None:
        return None
    if boost.expires_at is not None:
        boost.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()
    return boost


# --- admin CRUD -----------------------------------------------------------------------


async def create_product(
    session: AsyncSession,
    *,
    title: str,
    description: str,
    xtr_price: int,
    kind: str,
    multiplier_bp: int = 100,
    duration_hours: int = 0,
    stars_amount: int = 0,
) -> BoostProduct:
    if kind not in {item.value for item in BoostKind}:
        raise ValidationError("Неизвестный тип буста")
    if xtr_price < 1:
        raise ValidationError("Цена в XTR должна быть ≥ 1")
    if kind == BoostKind.STARS_PACK.value and stars_amount < 1:
        raise ValidationError("Для пака укажите количество Stars ≥ 1")
    if kind == BoostKind.MULTIPLIER.value and (multiplier_bp <= 100 or duration_hours < 1):
        raise ValidationError("Для множителя нужны множитель > 1.00 и длительность ≥ 1 ч")
    slug = await _unique_slug(session, slugify(title, prefix="boost_"))
    product = BoostProduct(
        slug=slug,
        title=title.strip()[:128],
        description=description.strip(),
        xtr_price=xtr_price,
        kind=kind,
        multiplier_bp=multiplier_bp if kind == BoostKind.MULTIPLIER.value else 100,
        duration_hours=duration_hours if kind == BoostKind.MULTIPLIER.value else 0,
        stars_amount=stars_amount if kind == BoostKind.STARS_PACK.value else 0,
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def update_product(session: AsyncSession, product_id: int, **fields) -> BoostProduct:
    product = await session.get(BoostProduct, product_id)
    if product is None:
        raise NotFound("Буст не найден")
    allowed = {"title", "description", "xtr_price", "stars_amount", "multiplier_bp", "duration_hours"}
    for key, value in fields.items():
        if key not in allowed:
            raise ValidationError(f"Поле {key} нельзя изменить")
        if key == "xtr_price" and int(value) < 1:
            raise ValidationError("Цена в XTR должна быть ≥ 1")
        setattr(product, key, value)
    await session.flush()
    return product


async def toggle_product(session: AsyncSession, product_id: int) -> BoostProduct:
    product = await session.get(BoostProduct, product_id)
    if product is None:
        raise NotFound("Буст не найден")
    product.is_active = not product.is_active
    await session.flush()
    return product


async def delete_product(session: AsyncSession, product_id: int) -> bool:
    """Hard-delete if never purchased, otherwise deactivate. Returns True when deleted."""
    product = await session.get(BoostProduct, product_id)
    if product is None:
        raise NotFound("Буст не найден")
    purchases = await session.execute(
        select(func.count()).select_from(UserBoost).where(UserBoost.product_id == product_id)
    )
    if int(purchases.scalar_one()) > 0:
        product.is_active = False
        await session.flush()
        return False
    await session.delete(product)
    await session.flush()
    return True


async def _unique_slug(session: AsyncSession, slug: str) -> str:
    candidate = slug
    counter = 2
    while True:
        exists = await session.execute(select(BoostProduct.id).where(BoostProduct.slug == candidate))
        if exists.scalar_one_or_none() is None:
            return candidate
        candidate = f"{slug}_{counter}"[:64]
        counter += 1
