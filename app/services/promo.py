import re
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerKind, PromoCode, PromoRedemption, User
from app.services import ledger, referrals
from app.services.antifraud import bump_activity, ensure_action_cooldown, ensure_not_banned
from app.services.errors import NotFound, PromoError, ValidationError

_CODE_RE = re.compile(r"^[A-Z0-9_-]{3,32}$")


def normalize_code(raw: str) -> str:
    return raw.strip().upper().replace(" ", "")


async def create_promo(
    session: AsyncSession,
    *,
    code: str,
    reward: int,
    max_uses: int = 0,
    expires_at: datetime | None = None,
    created_by: int | None = None,
) -> PromoCode:
    code = normalize_code(code)
    if not _CODE_RE.match(code):
        raise ValidationError("Код: 3–32 символа, латиница/цифры/_/-")
    if reward < 1:
        raise ValidationError("Награда должна быть ≥ 1 ⭐")
    if max_uses < 0:
        raise ValidationError("Лимит активаций не может быть отрицательным")
    exists = await session.execute(select(PromoCode.id).where(PromoCode.code == code))
    if exists.scalar_one_or_none() is not None:
        raise ValidationError("Такой код уже существует")
    promo = PromoCode(
        code=code,
        reward=reward,
        max_uses=max_uses,
        expires_at=expires_at,
        is_active=True,
        created_by=created_by,
    )
    session.add(promo)
    await session.flush()
    return promo


async def list_promos(session: AsyncSession, *, limit: int = 20, offset: int = 0) -> list[PromoCode]:
    result = await session.execute(
        select(PromoCode).order_by(PromoCode.id.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars().all())


async def count_promos(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(PromoCode))).scalar_one())


async def get_promo(session: AsyncSession, promo_id: int) -> PromoCode:
    promo = await session.get(PromoCode, promo_id)
    if promo is None:
        raise NotFound("Промокод не найден")
    return promo


async def toggle_promo(session: AsyncSession, promo_id: int) -> PromoCode:
    promo = await get_promo(session, promo_id)
    promo.is_active = not promo.is_active
    await session.flush()
    return promo


async def delete_promo(session: AsyncSession, promo_id: int) -> bool:
    promo = await get_promo(session, promo_id)
    used = await session.execute(
        select(func.count()).select_from(PromoRedemption).where(PromoRedemption.promo_id == promo_id)
    )
    if int(used.scalar_one()) > 0:
        promo.is_active = False
        await session.flush()
        return False
    await session.delete(promo)
    await session.flush()
    return True


async def redeem(
    session: AsyncSession,
    *,
    user: User,
    code: str,
    settings: Settings,
) -> tuple[PromoCode, int]:
    ensure_not_banned(user)
    ensure_action_cooldown(user, settings)
    code = normalize_code(code)
    result = await session.execute(select(PromoCode).where(PromoCode.code == code))
    promo = result.scalar_one_or_none()
    if promo is None or not promo.is_active:
        raise PromoError("Такого промокода нет или он выключен")
    if promo.expires_at is not None:
        expires = promo.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= datetime.now(UTC):
            raise PromoError("Срок действия промокода истёк")
    used_by_user = await session.execute(
        select(PromoRedemption.id).where(
            PromoRedemption.promo_id == promo.id, PromoRedemption.user_id == user.id
        )
    )
    if used_by_user.scalar_one_or_none() is not None:
        raise PromoError("Вы уже активировали этот промокод")

    # Atomic take of one slot: protects the limit under concurrent redemptions.
    stmt = update(PromoCode).where(PromoCode.id == promo.id).values(uses=PromoCode.uses + 1)
    if promo.max_uses > 0:
        stmt = stmt.where(PromoCode.uses < PromoCode.max_uses)
    taken = await session.execute(stmt.execution_options(synchronize_session="fetch"))
    if taken.rowcount == 0:
        raise PromoError("Лимит активаций промокода исчерпан")

    session.add(PromoRedemption(promo_id=promo.id, user_id=user.id, amount=promo.reward))
    await ledger.credit(
        session,
        user_id=user.id,
        amount=promo.reward,
        kind=LedgerKind.PROMO,
        reference=f"promo:{promo.code}"[:64],
        extra={"promo_id": promo.id},
    )
    await bump_activity(session, user, 1)
    await referrals.activate_if_ready(session, user=user, settings=settings)
    await session.flush()
    return promo, promo.reward
