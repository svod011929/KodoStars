import pytest

from app.db.models import BoostKind, LedgerKind, PaymentStatus, User
from app.db.seed import seed_catalog
from app.services import boosts, events, ledger, payments
from app.services import tasks as task_service
from app.services.economy import fulfill_boost_payment
from app.services.errors import ValidationError


async def _user(session, user_id: int) -> User:
    user = User(id=user_id, first_name=f"P{user_id}")
    session.add(user)
    await session.flush()
    return user


async def _products(session):
    await seed_catalog(session)
    # Isolate payment math from the seeded "first boost" auto-task.
    for task in await task_service.list_all_tasks(session):
        task.is_active = False
    await session.flush()
    items = await boosts.list_products(session)
    pack = next(p for p in items if p.kind == BoostKind.STARS_PACK.value)
    mult = next(p for p in items if p.kind == BoostKind.MULTIPLIER.value)
    return pack, mult


@pytest.mark.asyncio
async def test_fulfill_is_idempotent_per_charge(session, settings) -> None:
    pack, _ = await _products(session)
    user = await _user(session, 501)
    created = await fulfill_boost_payment(
        session, user=user, product=pack, telegram_charge_id="ch_1", settings=settings, xtr_amount=15
    )
    assert created is True
    assert await ledger.get_balance(session, user.id) == pack.stars_amount
    assert await payments.count_payments(session) == 1

    again = await fulfill_boost_payment(
        session, user=user, product=pack, telegram_charge_id="ch_1", settings=settings
    )
    assert again is False
    assert await ledger.get_balance(session, user.id) == pack.stars_amount
    assert await payments.count_payments(session) == 1
    assert await payments.revenue_xtr(session) == 15


@pytest.mark.asyncio
async def test_multiplier_purchase_activates_boost(session, settings) -> None:
    _, mult = await _products(session)
    user = await _user(session, 502)
    await fulfill_boost_payment(
        session, user=user, product=mult, telegram_charge_id="ch_2", settings=settings
    )
    assert await boosts.active_multiplier_bp(session, user.id) == mult.multiplier_bp
    assert len(await boosts.active_boosts(session, user.id)) == 1
    assert user.xp == 15 and user.activity_score == 2


@pytest.mark.asyncio
async def test_refund_pack_revokes_stars_and_notifies(session, settings) -> None:
    pack, _ = await _products(session)
    user = await _user(session, 503)
    await fulfill_boost_payment(
        session, user=user, product=pack, telegram_charge_id="ch_3", settings=settings
    )
    payment = await payments.get_by_charge(session, "ch_3")
    assert payment is not None
    calls: list[tuple[int, str]] = []

    async def ok(user_id: int, charge: str) -> bool:
        calls.append((user_id, charge))
        return True

    events.drain(session)
    await payments.refund(session, payment=payment, admin_id=1, refund_call=ok)
    assert calls == [(user.id, "ch_3")]
    assert payment.status == PaymentStatus.REFUNDED.value
    assert await ledger.get_balance(session, user.id) == 0
    kinds = [e.kind for e in await ledger.history(session, user.id)]
    assert LedgerKind.REFUND_REVOKE.value in kinds
    assert [e.name for e in events.peek(session)] == ["payment_refunded"]
    assert await payments.revenue_xtr(session) == 0

    with pytest.raises(ValidationError, match="уже возвращён"):
        await payments.refund(session, payment=payment, admin_id=1, refund_call=ok)


@pytest.mark.asyncio
async def test_refund_multiplier_expires_boost_and_failed_refund_keeps_state(session, settings) -> None:
    _, mult = await _products(session)
    user = await _user(session, 504)
    await fulfill_boost_payment(
        session, user=user, product=mult, telegram_charge_id="ch_4", settings=settings
    )
    payment = await payments.get_by_charge(session, "ch_4")

    async def fail(user_id: int, charge: str) -> bool:
        return False

    with pytest.raises(ValidationError, match="отклонил"):
        await payments.refund(session, payment=payment, admin_id=1, refund_call=fail)
    assert payment.status == PaymentStatus.PAID.value
    assert await boosts.active_multiplier_bp(session, user.id) == mult.multiplier_bp

    async def ok(user_id: int, charge: str) -> bool:
        return True

    await payments.refund(session, payment=payment, admin_id=1, refund_call=ok)
    assert await boosts.active_multiplier_bp(session, user.id) == 100


@pytest.mark.asyncio
async def test_product_crud(session) -> None:
    product = await boosts.create_product(
        session, title="Пак 100", description="", xtr_price=50, kind="stars_pack", stars_amount=100
    )
    assert product.slug.startswith("boost_")
    with pytest.raises(ValidationError):
        await boosts.create_product(
            session, title="x", description="", xtr_price=0, kind="stars_pack", stars_amount=1
        )
    with pytest.raises(ValidationError):
        await boosts.create_product(
            session,
            title="x",
            description="",
            xtr_price=5,
            kind="multiplier",
            multiplier_bp=100,
            duration_hours=1,
        )
    with pytest.raises(ValidationError):
        await boosts.create_product(session, title="x", description="", xtr_price=5, kind="weird")

    await boosts.update_product(session, product.id, xtr_price=60)
    assert product.xtr_price == 60
    await boosts.toggle_product(session, product.id)
    assert product.is_active is False
    assert await boosts.delete_product(session, product.id) is True
