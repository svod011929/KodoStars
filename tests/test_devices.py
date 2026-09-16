"""Anti-multiaccount service: fingerprints, twink linking, trust, gating."""

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import FraudEvent, LedgerKind, User
from app.services import devices, events, ledger, referrals, withdrawals
from app.services.antifraud import bump_activity
from app.services.errors import WithdrawalError

FP_A = "a" * 64
FP_B = "b" * 64


def _web_settings(**overrides) -> Settings:
    return Settings(
        admin_ids_raw="1",
        database_url="sqlite+aiosqlite://",
        signup_bonus=0,
        claim_cooldown_seconds=0,
        web_public_url="https://mini.example",
        **overrides,
    )


async def _user(session, user_id: int, **kwargs) -> User:
    user = User(id=user_id, first_name=f"U{user_id}", **kwargs)
    session.add(user)
    await session.flush()
    return user


async def _register(session, user: User, fp: str, settings: Settings, ip: str = "1.2.3.4"):
    return await devices.register_device(
        session,
        user=user,
        fingerprint=fp,
        ip=ip,
        user_agent="Mozilla/5.0 (Android)",
        platform="android",
        tg_version="8.0",
        signals={"ua": "Mozilla/5.0 (Android)", "screen": "1080x2400"},
        settings=settings,
    )


def test_settings_flags() -> None:
    off = Settings(admin_ids_raw="1", database_url="sqlite+aiosqlite://")
    assert off.web_enabled is False and off.device_check_active is False
    on = _web_settings()
    assert on.web_enabled and on.device_check_active
    assert on.web_url("verify") == "https://mini.example/verify"
    assert _web_settings(device_check_enabled=False).device_check_active is False
    http_only = Settings(admin_ids_raw="1", database_url="sqlite+aiosqlite://", web_public_url="http://x")
    assert http_only.web_enabled is False  # Mini Apps require HTTPS


def test_fingerprint_normalisation() -> None:
    assert devices.normalize_fingerprint(" ABC123 ") == "abc123"
    hashed = devices.normalize_fingerprint("not-hex!")
    assert len(hashed) == 64 and hashed == devices.normalize_fingerprint("not-hex!")
    with pytest.raises(Exception, match="Пустой"):
        devices.normalize_fingerprint("")
    same = devices.fingerprint_from_signals({"ua": "x", "screen": "1x1", "ignored": "z"})
    assert same == devices.fingerprint_from_signals({"screen": "1x1", "ua": "x"})
    assert devices.clean_signals({"ua": "x", "bogus": 1, "fonts": ["a", "b"]}) == {
        "ua": "x",
        "fonts": '["a", "b"]',
    }


@pytest.mark.asyncio
async def test_first_device_is_clean_second_account_is_twink(session) -> None:
    settings = _web_settings()
    first = await _user(session, 101)
    second = await _user(session, 102)
    events.drain(session)

    verdict = await _register(session, first, FP_A, settings)
    assert verdict.clean and verdict.first_time and verdict.matched_user_ids == []
    assert first.device_verified_at is not None and first.device_fp == FP_A and first.twink_of is None

    verdict = await _register(session, second, FP_A, settings)
    assert verdict.twink and verdict.matched_user_ids == [101]
    assert second.twink_of == 101 and second.is_twink
    kinds = (await session.execute(select(FraudEvent.kind))).scalars().all()
    assert "twink_device" in kinds
    assert [e.name for e in events.peek(session)] == ["device_verified", "device_verified"]
    assert events.peek(session)[1].payload["twink"] is True

    # Re-verification of the same account is idempotent and keeps the link.
    again = await _register(session, second, FP_A, settings)
    assert again.first_time is False and second.twink_of == 101

    linked = await devices.linked_accounts(session, first)
    assert [u.id for u in linked] == [102]
    clusters = await devices.clusters(session)
    assert clusters[0][0] == FP_A and clusters[0][1] == 2
    assert await devices.stats(session) == {"verified": 2, "twinks": 1, "trusted": 0}

    # Different device → independent account.
    third = await _user(session, 103)
    assert (await _register(session, third, FP_B, settings)).clean


@pytest.mark.asyncio
async def test_trust_clears_twink_flag(session) -> None:
    settings = _web_settings()
    first = await _user(session, 111)
    second = await _user(session, 112)
    await _register(session, first, FP_A, settings)
    await _register(session, second, FP_A, settings)
    assert second.is_twink
    await devices.set_trusted(session, second, True)
    assert second.is_trusted and second.twink_of is None and not second.is_twink
    # A trusted account no longer counts as a match for newcomers either.
    fourth = await _user(session, 114)
    await devices.set_trusted(session, first, True)
    assert (await _register(session, fourth, FP_A, settings)).clean


@pytest.mark.asyncio
async def test_ip_match_requirement(session) -> None:
    settings = _web_settings(twink_require_ip_match=True)
    first = await _user(session, 121)
    second = await _user(session, 122)
    third = await _user(session, 123)
    await _register(session, first, FP_A, settings, ip="10.0.0.1")
    assert (await _register(session, second, FP_A, settings, ip="10.0.0.2")).clean
    assert (await _register(session, third, FP_A, settings, ip="10.0.0.1")).twink


@pytest.mark.asyncio
async def test_referral_bonus_waits_for_verification_and_skips_twinks(session) -> None:
    settings = _web_settings(min_referral_activity=1)
    referrer = await _user(session, 131)
    referee = await _user(session, 132)
    await referrals.attach_referrer(session, user=referee, payload="ref_131", settings=settings)
    await bump_activity(session, referee, 1)

    # Activity threshold met but device not verified → nothing paid yet.
    assert await referrals.activate_if_ready(session, user=referee, settings=settings) == []
    assert await ledger.get_balance(session, referrer.id) == 0

    await _register(session, referee, FP_A, settings)
    credited = await referrals.activate_if_ready(session, user=referee, settings=settings)
    assert len(credited) == 1 and referee.referral_activated
    assert await ledger.get_balance(session, referrer.id) == settings.referral_l1_bonus

    # A second account on the same device never pays out.
    twink = await _user(session, 133)
    await referrals.attach_referrer(session, user=twink, payload="ref_131", settings=settings)
    await bump_activity(session, twink, 1)
    await _register(session, twink, FP_A, settings)
    assert twink.is_twink
    assert await referrals.activate_if_ready(session, user=twink, settings=settings) == []
    assert await ledger.get_balance(session, referrer.id) == settings.referral_l1_bonus

    # …unless an admin trusts it — then the pending bonus is paid on the next check.
    await devices.set_trusted(session, twink, True)
    assert len(await referrals.activate_if_ready(session, user=twink, settings=settings)) == 1
    assert await ledger.get_balance(session, referrer.id) == 2 * settings.referral_l1_bonus

    # With the check disabled the gate is transparent.
    plain = Settings(admin_ids_raw="1", database_url="sqlite+aiosqlite://", min_referral_activity=1)
    other = await _user(session, 134)
    await referrals.attach_referrer(session, user=other, payload="ref_131", settings=plain)
    await bump_activity(session, other, 1)
    assert len(await referrals.activate_if_ready(session, user=other, settings=plain)) == 1


@pytest.mark.asyncio
async def test_withdraw_requires_verification_and_can_block_twinks(session) -> None:
    settings = _web_settings(withdraw_cooldown_hours=0)
    user = await _user(session, 141)
    await ledger.credit(session, user_id=user.id, amount=200, kind=LedgerKind.TASK)
    with pytest.raises(WithdrawalError, match="Подтвердить устройство"):
        await withdrawals.apply(session, user=user, amount=50, settings=settings)

    relaxed = _web_settings(device_check_for_withdraw=False, withdraw_cooldown_hours=0)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=relaxed)
    await withdrawals.cancel(session, withdrawal=wd, user=user)

    await _register(session, user, FP_A, settings)
    wd = await withdrawals.apply(session, user=user, amount=50, settings=settings)
    await withdrawals.cancel(session, withdrawal=wd, user=user)

    twink = await _user(session, 142)
    await ledger.credit(session, user_id=twink.id, amount=200, kind=LedgerKind.TASK)
    await _register(session, twink, FP_A, settings)
    assert twink.is_twink
    # Default policy: withdrawal allowed, admin sees the warning in the card.
    wd = await withdrawals.apply(session, user=twink, amount=50, settings=settings)
    await withdrawals.cancel(session, withdrawal=wd, user=twink)
    strict = _web_settings(twink_block_withdraw=True, withdraw_cooldown_hours=0)
    with pytest.raises(WithdrawalError, match="другой аккаунт"):
        await withdrawals.apply(session, user=twink, amount=50, settings=strict)
