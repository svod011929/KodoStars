"""Ambassador program: slots, custom referral terms, daily promos."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    AmbassadorKind,
    AmbassadorStatus,
    AmbassadorSlot,
    PromoCode,
    User,
)
from app.services import promo as promo_service
from app.services.errors import EconomyError, NotFound, ValidationError

_ACTIVE = (AmbassadorStatus.PENDING.value, AmbassadorStatus.APPROVED.value)
_VALID_KINDS = {k.value for k in AmbassadorKind}


@dataclass(frozen=True)
class ReferralTerms:
    l1_bonus: int
    l1_percent: int
    l2_bonus: int
    l2_percent: int

    def bonus(self, level: int) -> int:
        if level == 1:
            return self.l1_bonus
        if level == 2:
            return self.l2_bonus
        return 0

    def percent(self, level: int) -> int:
        if level == 1:
            return self.l1_percent
        if level == 2:
            return self.l2_percent
        return 0


def normalize_invite_link(raw: str) -> str:
    return raw.strip().rstrip("/").lower()


def terms_from_settings(settings: Settings) -> ReferralTerms:
    return ReferralTerms(
        l1_bonus=settings.referral_l1_bonus,
        l1_percent=settings.referral_l1_percent,
        l2_bonus=settings.referral_l2_bonus,
        l2_percent=settings.referral_l2_percent,
    )


async def effective_referral_terms(
    session: AsyncSession,
    referrer_id: int,
    settings: Settings,
) -> ReferralTerms:
    """Max of each term field across the referrer's approved slots; else globals."""
    result = await session.execute(
        select(AmbassadorSlot).where(
            AmbassadorSlot.user_id == referrer_id,
            AmbassadorSlot.status == AmbassadorStatus.APPROVED.value,
        )
    )
    slots = list(result.scalars().all())
    if not slots:
        return terms_from_settings(settings)

    def _max(attr: str, fallback: int) -> int:
        values = [getattr(s, attr) for s in slots if getattr(s, attr) is not None]
        return max(values) if values else fallback

    base = terms_from_settings(settings)
    return ReferralTerms(
        l1_bonus=_max("l1_bonus", base.l1_bonus),
        l1_percent=_max("l1_percent", base.l1_percent),
        l2_bonus=_max("l2_bonus", base.l2_bonus),
        l2_percent=_max("l2_percent", base.l2_percent),
    )


def utc_day_key(now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).strftime("%Y-%m-%d")


def end_of_utc_day(now: datetime | None = None) -> datetime:
    stamp = now or datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    stamp = stamp.astimezone(UTC)
    tomorrow = datetime(stamp.year, stamp.month, stamp.day, tzinfo=UTC) + timedelta(days=1)
    return tomorrow


async def get_slot(session: AsyncSession, slot_id: int) -> AmbassadorSlot:
    slot = await session.get(AmbassadorSlot, slot_id)
    if slot is None:
        raise NotFound("Заявка не найдена")
    return slot


async def list_user_slots(session: AsyncSession, user_id: int) -> list[AmbassadorSlot]:
    result = await session.execute(
        select(AmbassadorSlot)
        .where(AmbassadorSlot.user_id == user_id)
        .order_by(AmbassadorSlot.id.desc())
    )
    return list(result.scalars().all())


async def list_by_status(
    session: AsyncSession, status: str, *, limit: int = 30
) -> list[AmbassadorSlot]:
    result = await session.execute(
        select(AmbassadorSlot)
        .where(AmbassadorSlot.status == status)
        .order_by(AmbassadorSlot.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_pending(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(AmbassadorSlot).where(
                    AmbassadorSlot.status == AmbassadorStatus.PENDING.value
                )
            )
        ).scalar_one()
    )


async def submit_application(
    session: AsyncSession,
    *,
    user: User,
    kind: str,
    title: str,
    invite_link: str,
) -> AmbassadorSlot:
    kind = kind.strip().lower()
    if kind not in _VALID_KINDS:
        raise ValidationError("Тип площадки: channel, chat или bot")
    title = title.strip()
    if not title or len(title) > 128:
        raise ValidationError("Название: 1–128 символов")
    link = normalize_invite_link(invite_link)
    if not link or len(link) > 512:
        raise ValidationError("Укажите ссылку на площадку")
    if "t.me/" not in link and not link.startswith("@"):
        raise ValidationError("Ссылка должна вести на Telegram (t.me/… или @username)")

    dup = await session.execute(
        select(AmbassadorSlot.id).where(
            AmbassadorSlot.user_id == user.id,
            AmbassadorSlot.invite_link == link,
            AmbassadorSlot.status.in_(_ACTIVE),
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise ValidationError("У вас уже есть заявка на эту площадку")

    slot = AmbassadorSlot(
        user_id=user.id,
        kind=kind,
        title=title,
        invite_link=link,
        status=AmbassadorStatus.PENDING.value,
    )
    session.add(slot)
    await session.flush()
    return slot


async def approve_slot(
    session: AsyncSession,
    *,
    slot_id: int,
    admin_id: int,
    l1_bonus: int,
    l1_percent: int,
    l2_bonus: int,
    l2_percent: int,
    promo_reward: int,
    promo_max_uses: int,
) -> AmbassadorSlot:
    slot = await get_slot(session, slot_id)
    if slot.status != AmbassadorStatus.PENDING.value:
        raise ValidationError("Одобрить можно только заявку на проверке")
    for name, value in (
        ("L1 бонус", l1_bonus),
        ("L1 %", l1_percent),
        ("L2 бонус", l2_bonus),
        ("L2 %", l2_percent),
        ("Награда промо", promo_reward),
    ):
        if value < 0:
            raise ValidationError(f"{name} не может быть отрицательным")
    if promo_reward < 1:
        raise ValidationError("Награда промокода должна быть ≥ 1")
    if promo_max_uses < 0:
        raise ValidationError("Лимит активаций не может быть отрицательным")
    if l1_percent > 100 or l2_percent > 100:
        raise ValidationError("Процент не может быть больше 100")

    slot.status = AmbassadorStatus.APPROVED.value
    slot.l1_bonus = l1_bonus
    slot.l1_percent = l1_percent
    slot.l2_bonus = l2_bonus
    slot.l2_percent = l2_percent
    slot.promo_reward = promo_reward
    slot.promo_max_uses = promo_max_uses
    slot.promo_auto_post = False
    slot.reviewed_by = admin_id
    slot.reviewed_at = datetime.now(UTC)
    slot.reject_reason = None
    await session.flush()
    return slot


async def reject_slot(
    session: AsyncSession,
    *,
    slot_id: int,
    admin_id: int,
    reason: str,
) -> AmbassadorSlot:
    slot = await get_slot(session, slot_id)
    if slot.status != AmbassadorStatus.PENDING.value:
        raise ValidationError("Отклонить можно только заявку на проверке")
    slot.status = AmbassadorStatus.REJECTED.value
    slot.reviewed_by = admin_id
    slot.reviewed_at = datetime.now(UTC)
    slot.reject_reason = (reason or "").strip()[:500] or "без причины"
    await session.flush()
    return slot


async def revoke_slot(
    session: AsyncSession,
    *,
    slot_id: int,
    admin_id: int,
) -> AmbassadorSlot:
    slot = await get_slot(session, slot_id)
    if slot.status != AmbassadorStatus.APPROVED.value:
        raise ValidationError("Отозвать можно только одобренный слот")
    slot.status = AmbassadorStatus.REVOKED.value
    slot.promo_auto_post = False
    slot.reviewed_by = admin_id
    slot.reviewed_at = datetime.now(UTC)
    await session.flush()
    return slot


async def update_slot_terms(
    session: AsyncSession,
    *,
    slot_id: int,
    l1_bonus: int,
    l1_percent: int,
    l2_bonus: int,
    l2_percent: int,
    promo_reward: int,
    promo_max_uses: int,
) -> AmbassadorSlot:
    slot = await get_slot(session, slot_id)
    if slot.status != AmbassadorStatus.APPROVED.value:
        raise ValidationError("Менять условия можно только у одобренного слота")
    if promo_reward < 1 or promo_max_uses < 0:
        raise ValidationError("Некорректные параметры промокода")
    if min(l1_bonus, l1_percent, l2_bonus, l2_percent) < 0:
        raise ValidationError("Условия не могут быть отрицательными")
    if l1_percent > 100 or l2_percent > 100:
        raise ValidationError("Процент не может быть больше 100")
    slot.l1_bonus = l1_bonus
    slot.l1_percent = l1_percent
    slot.l2_bonus = l2_bonus
    slot.l2_percent = l2_percent
    slot.promo_reward = promo_reward
    slot.promo_max_uses = promo_max_uses
    await session.flush()
    return slot


async def set_chat_id(session: AsyncSession, slot_id: int, chat_id: int) -> AmbassadorSlot:
    slot = await get_slot(session, slot_id)
    if slot.kind == AmbassadorKind.BOT.value:
        raise ValidationError("Для бота chat_id не нужен")
    slot.chat_id = chat_id
    await session.flush()
    return slot


async def todays_promo(session: AsyncSession, slot_id: int) -> PromoCode | None:
    day = utc_day_key()
    result = await session.execute(
        select(PromoCode).where(
            PromoCode.ambassador_slot_id == slot_id,
            PromoCode.promo_day_key == day,
        )
    )
    return result.scalar_one_or_none()


async def claim_daily_promo(
    session: AsyncSession,
    *,
    slot_id: int,
    user_id: int,
) -> PromoCode:
    slot = await get_slot(session, slot_id)
    if slot.user_id != user_id:
        raise ValidationError("Это не ваш слот")
    if slot.status != AmbassadorStatus.APPROVED.value:
        raise ValidationError("Слот не одобрен")
    if not slot.promo_reward or slot.promo_reward < 1:
        raise ValidationError("Админ ещё не задал параметры промокода")

    existing = await todays_promo(session, slot_id)
    if existing is not None:
        return existing

    day = utc_day_key()
    code = f"AMB{secrets.token_hex(4).upper()}"
    return await promo_service.create_promo(
        session,
        code=code,
        reward=int(slot.promo_reward),
        max_uses=int(slot.promo_max_uses or 0),
        expires_at=end_of_utc_day(),
        created_by=user_id,
        ambassador_slot_id=slot.id,
        promo_day_key=day,
    )


async def bot_is_chat_admin(bot: Bot, chat_id: int) -> bool:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
    except Exception:
        return False
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


async def enable_auto_post(session: AsyncSession, bot: Bot, slot_id: int) -> AmbassadorSlot:
    slot = await get_slot(session, slot_id)
    if slot.kind == AmbassadorKind.BOT.value:
        raise ValidationError("Автопост недоступен для типа «бот»")
    if slot.status != AmbassadorStatus.APPROVED.value:
        raise ValidationError("Слот не одобрен")
    if not slot.chat_id:
        raise ValidationError("Сначала укажите chat_id канала/чата")
    if not await bot_is_chat_admin(bot, slot.chat_id):
        raise ValidationError("Бот должен быть администратором в канале/чате")
    slot.promo_auto_post = True
    await session.flush()
    return slot


async def disable_auto_post(session: AsyncSession, slot_id: int) -> AmbassadorSlot:
    slot = await get_slot(session, slot_id)
    slot.promo_auto_post = False
    await session.flush()
    return slot


async def publish_promo(bot: Bot, slot: AmbassadorSlot, promo: PromoCode) -> None:
    if slot.kind == AmbassadorKind.BOT.value:
        raise ValidationError("Автопост недоступен для бота")
    if not slot.chat_id:
        raise ValidationError("Не указан chat_id")
    if not await bot_is_chat_admin(bot, slot.chat_id):
        raise ValidationError("Бот не админ в канале/чате — автопост выключен")
    text = (
        f"🎟 Промокод <b>{promo.code}</b>\n"
        f"Награда: <b>{promo.reward}</b> ⭐"
        + (f" · до {promo.max_uses} активаций" if promo.max_uses else "")
        + "\nАктивируйте в боте."
    )
    try:
        await bot.send_message(slot.chat_id, text)
    except Exception as exc:
        raise EconomyError(f"Не удалось опубликовать: {exc}") from exc
