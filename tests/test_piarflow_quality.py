"""PiarFlow issued / credited sponsor tracking and admin aggregates."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import PiarflowIssuedSub, PiarflowPaidSub, PiarflowUnsub, User
from app.op.base import OpResult, Sponsor
from app.services import piarflow_quality


async def _user(session, user_id: int) -> User:
    user = User(id=user_id, first_name=f"U{user_id}")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_record_issued_upserts_show_count(session) -> None:
    from sqlalchemy import select

    await _user(session, 1)
    n = await piarflow_quality.record_issued_sponsors(
        session, 1, ["https://t.me/a", "https://t.me/b", "https://t.me/a"]
    )
    assert n == 2
    rows = list((await session.execute(select(PiarflowIssuedSub))).scalars().all())
    by_link = {r.offer_link: r for r in rows}
    assert by_link["https://t.me/a"].show_count == 2
    assert by_link["https://t.me/b"].show_count == 1

    n2 = await piarflow_quality.record_issued_sponsors(session, 1, ["https://t.me/a"])
    assert n2 == 0
    await session.refresh(by_link["https://t.me/a"])
    assert by_link["https://t.me/a"].show_count == 3


@pytest.mark.asyncio
async def test_record_from_op_result_issued_and_paid(session) -> None:
    await _user(session, 2)
    result = OpResult.blocked(
        "piarflow",
        [Sponsor(title="@a", url="https://t.me/a"), Sponsor(title="@b", url="https://t.me/b")],
        paid_links=["https://t.me/paid"],
    )
    issued, paid = await piarflow_quality.record_from_op_result(session, 2, result)
    assert issued == 2 and paid == 1
    assert await piarflow_quality.paid_sub_count(session, 2) == 1
    assert await piarflow_quality.issued_sub_count(session, 2) == 2


@pytest.mark.asyncio
async def test_traffic_stats_windows(session) -> None:
    await _user(session, 10)
    await _user(session, 11)
    now = datetime.now(UTC)
    session.add_all(
        [
            PiarflowIssuedSub(
                user_id=10,
                offer_link="https://t.me/x",
                show_count=2,
                first_shown_at=now - timedelta(hours=1),
                last_shown_at=now - timedelta(hours=1),
            ),
            PiarflowIssuedSub(
                user_id=11,
                offer_link="https://t.me/y",
                show_count=1,
                first_shown_at=now - timedelta(days=3),
                last_shown_at=now - timedelta(days=3),
            ),
            PiarflowPaidSub(user_id=10, offer_link="https://t.me/x", created_at=now - timedelta(hours=1)),
            PiarflowPaidSub(user_id=11, offer_link="https://t.me/z", created_at=now - timedelta(days=10)),
            PiarflowUnsub(tg_user_id=10, offer_link="https://t.me/x", penalty=5),
        ]
    )
    await session.flush()

    traffic = await piarflow_quality.traffic_stats(session)
    assert traffic.issued_total == 2
    assert traffic.issued_today == 1
    assert traffic.issued_7d == 2
    assert traffic.shows_total == 3
    assert traffic.credited_total == 2
    assert traffic.credited_today == 1
    assert traffic.credited_7d == 1
    assert traffic.unsubs_total == 1
    assert traffic.unique_users_issued == 2
    assert traffic.unique_users_credited == 2
    assert traffic.conversion_pct == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_list_recent_issued_and_credited(session) -> None:
    await _user(session, 20)
    await piarflow_quality.record_issued_sponsors(session, 20, ["https://t.me/one"])
    await piarflow_quality.record_paid_subs(session, 20, ["https://t.me/one"])
    issued = await piarflow_quality.list_issued(session, limit=10, offset=0)
    credited = await piarflow_quality.list_credited(session, limit=10, offset=0)
    assert len(issued) == 1 and issued[0].offer_link == "https://t.me/one"
    assert len(credited) == 1 and credited[0].offer_link == "https://t.me/one"
