"""Ambassador program: slots, custom referral terms, daily promos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AmbassadorStatus, AmbassadorSlot


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
