from datetime import timedelta

import pytest

from app.db.models import LedgerKind, User
from app.services import daily, ledger, referrals
from app.services.errors import AlreadyClaimed, UserBanned


async def _user(session, user_id: int = 300) -> User:
    user = User(id=user_id, first_name="D")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_first_claim_pays_base_and_starts_streak(session, settings) -> None:
    user = await _user(session)
    preview = await daily.preview(session, user=user, settings=settings)
    assert preview.claimed_today is False
    assert preview.streak_if_claimed == 1
    assert preview.estimated_reward == settings.daily_base_reward

    claim = await daily.claim_daily(session, user=user, settings=settings)
    assert claim.amount == settings.daily_base_reward
    assert claim.streak == 1
    assert user.streak == 1
    assert user.xp == 10
    assert await ledger.get_balance(session, user.id) == settings.daily_base_reward
    entries = await ledger.history(session, user.id)
    assert entries[0].kind == LedgerKind.DAILY.value


@pytest.mark.asyncio
async def test_second_claim_same_day_rejected(session, settings) -> None:
    user = await _user(session, 301)
    await daily.claim_daily(session, user=user, settings=settings)
    with pytest.raises(AlreadyClaimed):
        await daily.claim_daily(session, user=user, settings=settings)
    preview = await daily.preview(session, user=user, settings=settings)
    assert preview.claimed_today is True
    assert preview.streak_if_claimed == 2
    assert 0 < preview.seconds_until_reset <= 86400


@pytest.mark.asyncio
async def test_streak_continues_and_resets(session, settings) -> None:
    user = await _user(session, 302)
    today = daily.utc_today()
    user.last_daily_on = today - timedelta(days=1)
    user.streak = 4
    assert daily.next_streak(user, today) == 5
    user.last_daily_on = today - timedelta(days=3)
    assert daily.next_streak(user, today) == 1
    user.last_daily_on = None
    assert daily.next_streak(user, today) == 1


@pytest.mark.asyncio
async def test_streak_bonus_is_capped(session, settings) -> None:
    assert daily.base_reward_for(1, settings) == settings.daily_base_reward
    assert daily.base_reward_for(3, settings) == settings.daily_base_reward + 2 * settings.daily_streak_bonus
    capped = settings.daily_base_reward + settings.daily_streak_cap * settings.daily_streak_bonus
    assert daily.base_reward_for(50, settings) == capped


@pytest.mark.asyncio
async def test_banned_user_cannot_claim(session, settings) -> None:
    user = await _user(session, 303)
    user.is_banned = True
    with pytest.raises(UserBanned):
        await daily.claim_daily(session, user=user, settings=settings)


@pytest.mark.asyncio
async def test_claim_activates_referral_and_shares(session, settings) -> None:
    referrer = await _user(session, 304)
    referee = await _user(session, 305)
    await referrals.attach_referrer(session, user=referee, payload="ref_304", settings=settings)
    referee.activity_score = settings.min_referral_activity - 1
    await daily.claim_daily(session, user=referee, settings=settings)
    assert referee.referral_activated is True
    # Activation bonus + 15 % share of the daily reward.
    expected_share = (settings.daily_base_reward * settings.referral_l1_percent) // 100
    assert await ledger.get_balance(session, referrer.id) == settings.referral_l1_bonus + expected_share
