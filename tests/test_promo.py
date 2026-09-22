from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import User
from app.services import antifraud, ledger, promo
from app.services.errors import CooldownActive, PromoError, ValidationError


async def _user(session, user_id: int) -> User:
    user = User(id=user_id, first_name=f"U{user_id}")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_create_validation(session) -> None:
    code = await promo.create_promo(session, code=" welcome-2026 ", reward=10, max_uses=2)
    assert code.code == "WELCOME-2026"
    for kwargs in (
        {"code": "ab", "reward": 1},
        {"code": "плохой", "reward": 1},
        {"code": "OKCODE", "reward": 0},
        {"code": "OKCODE", "reward": 1, "max_uses": -1},
        {"code": "WELCOME-2026", "reward": 1},
    ):
        with pytest.raises(ValidationError):
            await promo.create_promo(session, **kwargs)


@pytest.mark.asyncio
async def test_redeem_flow_and_limits(session, settings) -> None:
    code = await promo.create_promo(session, code="GIFT", reward=25, max_uses=2)
    a = await _user(session, 601)
    b = await _user(session, 602)
    c = await _user(session, 603)

    used, amount = await promo.redeem(session, user=a, code="gift", settings=settings)
    assert used.id == code.id and amount == 25
    assert await ledger.get_balance(session, a.id) == 25
    assert code.uses == 1
    with pytest.raises(PromoError, match="уже активировали"):
        await promo.redeem(session, user=a, code="GIFT", settings=settings)

    await promo.redeem(session, user=b, code="GIFT", settings=settings)
    with pytest.raises(PromoError, match="Лимит"):
        await promo.redeem(session, user=c, code="GIFT", settings=settings)
    assert await ledger.get_balance(session, c.id) == 0


@pytest.mark.asyncio
async def test_inactive_expired_unknown(session, settings) -> None:
    user = await _user(session, 604)
    with pytest.raises(PromoError, match="нет"):
        await promo.redeem(session, user=user, code="NOPE", settings=settings)

    expired = await promo.create_promo(
        session, code="OLD", reward=5, expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    with pytest.raises(PromoError, match="истёк"):
        await promo.redeem(session, user=user, code=expired.code, settings=settings)

    off = await promo.create_promo(session, code="OFF", reward=5)
    await promo.toggle_promo(session, off.id)
    with pytest.raises(PromoError):
        await promo.redeem(session, user=user, code="OFF", settings=settings)


@pytest.mark.asyncio
async def test_delete_with_redemptions_deactivates(session, settings) -> None:
    code = await promo.create_promo(session, code="USED", reward=5)
    user = await _user(session, 605)
    await promo.redeem(session, user=user, code="USED", settings=settings)
    assert await promo.delete_promo(session, code.id) is False
    assert code.is_active is False
    fresh = await promo.create_promo(session, code="FRESH", reward=5)
    assert await promo.delete_promo(session, fresh.id) is True
    assert await promo.count_promos(session) == 1


@pytest.mark.asyncio
async def test_redeem_skip_cooldown_for_deeplink(session, settings) -> None:
    """Activate deep-link must credit even if /start just stamped earn cooldown."""
    antifraud.clear_earn_cooldowns()
    cooled = settings.model_copy(update={"claim_cooldown_seconds": 10})
    await promo.create_promo(session, code="LINK5", reward=5)
    user = await _user(session, 606)
    await antifraud.bump_activity(session, user, 1)
    with pytest.raises(CooldownActive):
        await promo.redeem(session, user=user, code="LINK5", settings=cooled)
    promo_row, amount = await promo.redeem(
        session, user=user, code="LINK5", settings=cooled, skip_cooldown=True
    )
    assert promo_row.code == "LINK5" and amount == 5
    assert await ledger.get_balance(session, user.id) == 5
