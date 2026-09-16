import csv
from io import StringIO

import pytest
from sqlalchemy import select

from app.db.models import BoostProduct, LedgerKind, User
from app.db.seed import seed_catalog
from app.services import daily, export, leaderboard, ledger, promo, referrals, stats, withdrawals
from app.services.antifraud import bump_activity, record_event, suspicious_referrers
from app.services.economy import fulfill_boost_payment


async def _user(session, user_id: int, **kwargs) -> User:
    user = User(id=user_id, first_name=f"S{user_id}", **kwargs)
    session.add(user)
    await session.flush()
    return user


async def _build_world(session, settings) -> None:
    await seed_catalog(session)
    root = await _user(session, 701, username="root_user")
    for uid in range(702, 708):
        u = await _user(session, uid)
        await referrals.attach_referrer(session, user=u, payload="ref_701", settings=settings)
        if uid % 2 == 0:
            await bump_activity(session, u, settings.min_referral_activity)
            await referrals.activate_if_ready(session, user=u, settings=settings)
    await daily.claim_daily(session, user=root, settings=settings)
    await ledger.credit(session, user_id=702, amount=100, kind=LedgerKind.TASK)
    wd = await withdrawals.apply(session, user=(await session.get(User, 702)), amount=50, settings=settings)
    await withdrawals.approve_manual(session, withdrawal=wd, admin_id=1)
    await withdrawals.confirm_sent(session, withdrawal=wd, admin_id=1)
    products = await session.execute(select(BoostProduct))
    pack = next(p for p in products.scalars() if p.kind == "stars_pack")
    await fulfill_boost_payment(session, user=root, product=pack, telegram_charge_id="c1", settings=settings)
    code = await promo.create_promo(session, code="STAT", reward=3)
    await promo.redeem(session, user=(await session.get(User, 703)), code=code.code, settings=settings)
    await record_event(session, 703, "self_referral", "test")


@pytest.mark.asyncio
async def test_dashboard_numbers(session, settings) -> None:
    await _build_world(session, settings)
    d = await stats.dashboard(session)
    assert d.users_total == 7
    assert d.users_today == 7
    assert d.referred == 6
    assert d.activated == 3
    assert d.activation_rate == 50.0
    assert d.withdraw_sent_count == 1 and d.withdraw_sent_sum == 50
    assert d.payments_count == 1 and d.revenue_xtr == 15
    assert d.daily_claims_today == 1
    assert d.promo_redemptions == 1
    assert d.credited_by_kind[LedgerKind.PROMO.value] == 3
    assert d.credited_total == sum(d.credited_by_kind.values())
    total_balance = sum([await ledger.get_balance(session, uid) for uid in range(701, 708)])
    assert d.total_balance == total_balance
    days = await stats.registrations_by_day(session, days=7)
    assert sum(count for _, count in days) == 7


@pytest.mark.asyncio
async def test_leaderboard_and_masking(session, settings) -> None:
    await _build_world(session, settings)
    top = await leaderboard.top_referrers(session, limit=5)
    assert top[0].user_id == 701 and top[0].value == 6
    assert top[0].name == "@ro***r"
    earners = await leaderboard.top_earners(session, limit=5, days=7)
    assert earners[0].user_id in {701, 702}
    assert await leaderboard.user_rank_by_referrals(session, 701) == 1
    assert await leaderboard.user_rank_by_referrals(session, 702) is None
    short = User(id=1, first_name="Al")
    assert leaderboard.mask_name(short) == "A***"


@pytest.mark.asyncio
async def test_suspicious_referrers(session, settings) -> None:
    await _build_world(session, settings)
    rows = await suspicious_referrers(session, min_referrals=5)
    assert len(rows) == 1
    user, total, activated = rows[0]
    assert (user.id, total, activated) == (701, 6, 3)


@pytest.mark.asyncio
async def test_csv_exports(session, settings) -> None:
    await _build_world(session, settings)
    users_csv = await export.users_csv(session)
    assert users_csv.startswith("\ufeff".encode("utf-8"))
    rows = list(csv.reader(StringIO(users_csv.decode("utf-8-sig"))))
    assert rows[0][:3] == ["id", "username", "first_name"]
    assert len(rows) == 8
    wd_rows = list(csv.reader(StringIO((await export.withdrawals_csv(session)).decode("utf-8-sig"))))
    assert wd_rows[1][3] == "sent"
    ledger_rows = list(
        csv.reader(StringIO((await export.ledger_csv(session, user_id=703)).decode("utf-8-sig")))
    )
    assert all(row[1] == "703" for row in ledger_rows[1:])
    pay_rows = list(csv.reader(StringIO((await export.payments_csv(session)).decode("utf-8-sig"))))
    assert pay_rows[1][3] == "15"
