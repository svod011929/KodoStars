import pytest

from app.db.models import LedgerKind, User
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
    await referrals.attach_referrer(
        session, user=mid, payload=f"ref_{root.id}", settings=settings
    )
    await referrals.attach_referrer(
        session, user=leaf, payload=f"ref_{mid.id}", settings=settings
    )
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
    edges = await referrals.attach_referrer(
        session, user=user, payload="ref_9", settings=settings
    )
    assert edges == []
    assert user.referred_by_id is None


@pytest.mark.asyncio
async def test_bonus_waits_for_min_activity(session, settings) -> None:
    referrer = await _make_user(session, 10)
    referee = await _make_user(session, 11)
    await referrals.attach_referrer(
        session, user=referee, payload="ref_10", settings=settings
    )
    credited = await referrals.activate_if_ready(
        session, user=referee, settings=settings
    )
    assert credited == []
    assert await ledger.get_balance(session, referrer.id) == 0

    await bump_activity(session, referee, settings.min_referral_activity)
    credited = await referrals.activate_if_ready(
        session, user=referee, settings=settings
    )
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
    await referrals.share_earning(
        session, earner=leaf, base_amount=100, settings=settings, source="daily"
    )
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
