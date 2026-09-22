"""Ambassador slots: terms resolver, lifecycle, daily promos."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AmbassadorKind, AmbassadorStatus, AmbassadorSlot, User
from app.services import ambassadors as amb


@pytest.mark.asyncio
async def test_effective_terms_defaults_to_settings(session: AsyncSession, settings: Settings) -> None:
    session.add(User(id=10, first_name="A"))
    await session.commit()
    terms = await amb.effective_referral_terms(session, 10, settings)
    assert terms.l1_bonus == settings.referral_l1_bonus
    assert terms.l1_percent == settings.referral_l1_percent
    assert terms.l2_bonus == settings.referral_l2_bonus
    assert terms.l2_percent == settings.referral_l2_percent


@pytest.mark.asyncio
async def test_effective_terms_takes_max_across_approved_slots(
    session: AsyncSession, settings: Settings
) -> None:
    session.add(User(id=10, first_name="A"))
    await session.flush()
    session.add_all(
        [
            AmbassadorSlot(
                user_id=10,
                kind=AmbassadorKind.CHANNEL.value,
                title="C1",
                invite_link="https://t.me/c1",
                status=AmbassadorStatus.APPROVED.value,
                l1_bonus=20,
                l1_percent=10,
                l2_bonus=1,
                l2_percent=2,
                promo_reward=5,
                promo_max_uses=10,
            ),
            AmbassadorSlot(
                user_id=10,
                kind=AmbassadorKind.CHAT.value,
                title="C2",
                invite_link="https://t.me/c2",
                status=AmbassadorStatus.APPROVED.value,
                l1_bonus=15,
                l1_percent=25,
                l2_bonus=5,
                l2_percent=1,
                promo_reward=5,
                promo_max_uses=10,
            ),
            AmbassadorSlot(
                user_id=10,
                kind=AmbassadorKind.BOT.value,
                title="B",
                invite_link="https://t.me/b",
                status=AmbassadorStatus.REVOKED.value,
                l1_bonus=100,
                l1_percent=90,
                l2_bonus=50,
                l2_percent=40,
                promo_reward=5,
                promo_max_uses=10,
            ),
        ]
    )
    await session.commit()
    terms = await amb.effective_referral_terms(session, 10, settings)
    assert (terms.l1_bonus, terms.l1_percent, terms.l2_bonus, terms.l2_percent) == (20, 25, 5, 2)


def test_normalize_invite_link() -> None:
    assert amb.normalize_invite_link(" https://T.ME/Foo/ ") == "https://t.me/foo"
