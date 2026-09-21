import pytest
from sqlalchemy import func, select

from app.db.models import FraudEvent, LedgerKind, ReferralEdge, User
from app.services import ledger, referrals
from app.services.antifraud import bump_activity


async def _make_user(session, user_id: int, referred_by: int | None = None) -> User:
    user = User(id=user_id, first_name=f"U{user_id}", referred_by_id=referred_by)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_parse_ref_payload() -> None:
    assert referrals.parse_ref_payload("ref_42") == 42
    assert referrals.parse_ref_payload("42") == 42
    assert referrals.parse_ref_payload("start") is None
    assert referrals.parse_ref_payload(None) is None


@pytest.mark.asyncio
async def test_attach_two_levels(session, settings) -> None:
    root = await _make_user(session, 1)
    mid = await _make_user(session, 2)
    leaf = await _make_user(session, 3)
    await referrals.attach_referrer(session, user=mid, payload=f"ref_{root.id}", settings=settings)
    await referrals.attach_referrer(session, user=leaf, payload=f"ref_{mid.id}", settings=settings)
    assert mid.referred_by_id == 1
    assert leaf.referred_by_id == 2
    stats_root = await referrals.referral_stats(session, 1)
    assert stats_root[1] == 1
    assert stats_root[2] == 1
    stats_mid = await referrals.referral_stats(session, 2)
    assert stats_mid[1] == 1
    assert stats_mid[2] == 0


@pytest.mark.asyncio
async def test_self_referral_blocked(session, settings) -> None:
    user = await _make_user(session, 9)
    edges = await referrals.attach_referrer(session, user=user, payload="ref_9", settings=settings)
    assert edges == []
    assert user.referred_by_id is None


@pytest.mark.asyncio
async def test_bonus_waits_for_min_activity(session, settings) -> None:
    referrer = await _make_user(session, 10)
    referee = await _make_user(session, 11)
    await referrals.attach_referrer(session, user=referee, payload="ref_10", settings=settings)
    credited = await referrals.activate_if_ready(session, user=referee, settings=settings)
    assert credited == []
    assert await ledger.get_balance(session, referrer.id) == 0

    await bump_activity(session, referee, settings.min_referral_activity)
    credited = await referrals.activate_if_ready(session, user=referee, settings=settings)
    assert len(credited) == 1
    assert referee.referral_activated is True
    assert await ledger.get_balance(session, referrer.id) == settings.referral_l1_bonus


@pytest.mark.asyncio
async def test_earning_share_after_activation(session, settings) -> None:
    root = await _make_user(session, 20)
    mid = await _make_user(session, 21)
    leaf = await _make_user(session, 22)
    await referrals.attach_referrer(session, user=mid, payload="ref_20", settings=settings)
    await referrals.attach_referrer(session, user=leaf, payload="ref_21", settings=settings)
    await bump_activity(session, mid, settings.min_referral_activity)
    await bump_activity(session, leaf, settings.min_referral_activity)
    await referrals.activate_if_ready(session, user=mid, settings=settings)
    await referrals.activate_if_ready(session, user=leaf, settings=settings)

    await ledger.credit(session, user_id=leaf.id, amount=100, kind=LedgerKind.DAILY)
    await referrals.share_earning(session, earner=leaf, base_amount=100, settings=settings, source="daily")
    # L1 15% to mid, L2 5% to root — plus activation bonuses already paid
    assert await ledger.get_balance(session, mid.id) == settings.referral_l1_bonus + 15
    assert await ledger.get_balance(session, root.id) == (
        settings.referral_l1_bonus + settings.referral_l2_bonus + 5
    )


@pytest.mark.asyncio
async def test_second_start_does_not_rebind_referrer(session, settings) -> None:
    await _make_user(session, 30)
    await _make_user(session, 31)
    user = await _make_user(session, 32)
    await referrals.attach_referrer(session, user=user, payload="ref_30", settings=settings)
    await referrals.attach_referrer(session, user=user, payload="ref_31", settings=settings)
    assert user.referred_by_id == 30


@pytest.mark.asyncio
async def test_attach_is_idempotent_when_edge_exists_without_referred_by(session, settings) -> None:
    """State left by a pre-serialisation race: the edge row exists, referred_by_id is NULL.

    Re-attaching must not raise the UNIQUE violation from the incident report; it repairs
    ``referred_by_id`` from the existing edge and records a fraud event.
    """
    referrer = await _make_user(session, 8531170754)
    other = await _make_user(session, 40)
    user = await _make_user(session, 8594083493)
    session.add(ReferralEdge(referrer_id=referrer.id, referee_id=user.id, level=1))
    await session.flush()

    edges = await referrals.attach_referrer(
        session, user=user, payload=f"ref_{referrer.id}", settings=settings
    )
    assert edges == []
    assert user.referred_by_id == referrer.id
    total = await session.execute(select(func.count()).select_from(ReferralEdge))
    assert int(total.scalar_one()) == 1
    kinds = (await session.execute(select(FraudEvent.kind))).scalars().all()
    assert "referral_repaired" in kinds

    # And a stale link to someone else cannot re-attribute the account either.
    await referrals.attach_referrer(session, user=user, payload=f"ref_{other.id}", settings=settings)
    assert user.referred_by_id == referrer.id


@pytest.mark.asyncio
async def test_bonus_requires_piarflow_paid_subs(session, settings) -> None:
    from app.services import piarflow_quality

    gated = settings.model_copy(update={"referral_min_piarflow_subs": 2, "min_referral_activity": 1})
    referrer = await _make_user(session, 60)
    referee = await _make_user(session, 61)
    await referrals.attach_referrer(session, user=referee, payload="ref_60", settings=gated)
    await bump_activity(session, referee, gated.min_referral_activity)

    assert await referrals.activate_if_ready(session, user=referee, settings=gated) == []
    assert await ledger.get_balance(session, referrer.id) == 0

    await piarflow_quality.record_paid_subs(session, referee.id, ["https://t.me/a"])
    assert await referrals.activate_if_ready(session, user=referee, settings=gated) == []

    await piarflow_quality.record_paid_subs(session, referee.id, ["https://t.me/b"])
    credited = await referrals.activate_if_ready(session, user=referee, settings=gated)
    assert len(credited) == 1
    assert referee.referral_activated is True
    assert await ledger.get_balance(session, referrer.id) == gated.referral_l1_bonus


@pytest.mark.asyncio
async def test_attach_chain_stops_on_cycle(session, settings) -> None:
    a = await _make_user(session, 50)
    b = await _make_user(session, 51, referred_by=50)
    a.referred_by_id = 51  # corrupted cycle a ↔ b must not loop or duplicate edges
    await session.flush()
    leaf = await _make_user(session, 52)
    edges = await referrals.attach_referrer(session, user=leaf, payload="ref_51", settings=settings)
    assert [(e.referrer_id, e.level) for e in edges] == [(51, 1), (50, 2)]
    assert b.id == 51
