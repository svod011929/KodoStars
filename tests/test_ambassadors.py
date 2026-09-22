"""Ambassador slots: terms resolver, lifecycle, daily promos."""

from __future__ import annotations

import pytest
from sqlalchemy import select
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


@pytest.mark.asyncio
async def test_submit_approve_claim_daily_and_revoke(session: AsyncSession, settings: Settings) -> None:
    from app.services.errors import ValidationError

    user = User(id=10, first_name="A")
    session.add(user)
    await session.flush()

    slot = await amb.submit_application(
        session,
        user=user,
        kind="channel",
        title="My Chan",
        invite_link="https://t.me/MyChan",
    )
    assert slot.status == AmbassadorStatus.PENDING.value
    assert slot.invite_link == "https://t.me/mychan"

    with pytest.raises(ValidationError):
        await amb.submit_application(
            session, user=user, kind="channel", title="Dup", invite_link="https://t.me/mychan/"
        )

    approved = await amb.approve_slot(
        session,
        slot_id=slot.id,
        admin_id=1,
        l1_bonus=50,
        l1_percent=30,
        l2_bonus=7,
        l2_percent=8,
        promo_reward=12,
        promo_max_uses=25,
    )
    assert approved.status == AmbassadorStatus.APPROVED.value
    assert approved.promo_reward == 12

    first = await amb.claim_daily_promo(session, slot_id=slot.id, user_id=10)
    second = await amb.claim_daily_promo(session, slot_id=slot.id, user_id=10)
    assert first.id == second.id
    assert first.code.startswith("AMB")
    assert first.ambassador_slot_id == slot.id
    assert first.reward == 12
    assert first.max_uses == 25

    terms = await amb.effective_referral_terms(session, 10, settings)
    assert terms.l1_bonus == 50 and terms.l1_percent == 30

    await amb.revoke_slot(session, slot_id=slot.id, admin_id=1)
    terms2 = await amb.effective_referral_terms(session, 10, settings)
    assert terms2.l1_bonus == settings.referral_l1_bonus


@pytest.mark.asyncio
async def test_referral_bonus_uses_ambassador_terms(session: AsyncSession, settings: Settings) -> None:
    from app.db.models import LedgerEntry, LedgerKind, ReferralEdge
    from app.services import referrals

    settings.referral_min_piarflow_subs = 0
    settings.device_check_enabled = False
    settings.min_referral_activity = 0

    referrer = User(id=100, first_name="Ref", xp=0)
    referee = User(
        id=101,
        first_name="Ee",
        referred_by_id=100,
        referral_activated=False,
        activity_score=10,
    )
    session.add_all([referrer, referee])
    await session.flush()
    session.add(ReferralEdge(referrer_id=100, referee_id=101, level=1))
    await amb.submit_application(
        session, user=referrer, kind="bot", title="B", invite_link="https://t.me/ambot"
    )
    slots = await amb.list_user_slots(session, 100)
    await amb.approve_slot(
        session,
        slot_id=slots[0].id,
        admin_id=1,
        l1_bonus=77,
        l1_percent=15,
        l2_bonus=3,
        l2_percent=5,
        promo_reward=5,
        promo_max_uses=10,
    )
    await session.commit()

    await referrals.activate_if_ready(session, user=referee, settings=settings, boost_bp=100)
    await session.commit()

    result = await session.execute(
        select(LedgerEntry).where(
            LedgerEntry.user_id == 100, LedgerEntry.kind == LedgerKind.REFERRAL_BONUS.value
        )
    )
    entry = result.scalar_one()
    assert entry.amount == 77
