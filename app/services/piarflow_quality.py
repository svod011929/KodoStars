"""Track PiarFlow sponsors that were issued and those that were paid (subscribed).

Referral activation requires a minimum number of paid subscriptions. Admin traffic
stats compare issued inventory vs credited sales.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PiarflowIssuedSub, PiarflowPaidSub, PiarflowUnsub
from app.op.base import OpResult

log = structlog.get_logger("kodostars.piarflow_quality")


@dataclass(slots=True)
class PiarflowTraffic:
    issued_total: int = 0
    issued_today: int = 0
    issued_7d: int = 0
    shows_total: int = 0
    credited_total: int = 0
    credited_today: int = 0
    credited_7d: int = 0
    unsubs_total: int = 0
    unsubs_today: int = 0
    unique_users_issued: int = 0
    unique_users_credited: int = 0

    @property
    def conversion_pct(self) -> float:
        return (self.credited_total / self.issued_total * 100) if self.issued_total else 0.0


async def record_issued_sponsors(session: AsyncSession, user_id: int, links: list[str]) -> int:
    """Upsert issued offer links. Returns how many *new* rows were added."""
    added = 0
    now = datetime.now(UTC)
    counts: Counter[str] = Counter()
    for raw in links:
        link = (raw or "").strip()[:512]
        if link:
            counts[link] += 1
    for link, times in counts.items():
        result = await session.execute(
            select(PiarflowIssuedSub).where(
                PiarflowIssuedSub.user_id == user_id,
                PiarflowIssuedSub.offer_link == link,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            session.add(
                PiarflowIssuedSub(
                    user_id=user_id,
                    offer_link=link,
                    show_count=times,
                    first_shown_at=now,
                    last_shown_at=now,
                )
            )
            added += 1
        else:
            row.show_count = int(row.show_count or 0) + times
            row.last_shown_at = now
    if counts:
        await session.flush()
        log.info(
            "piarflow_issued",
            user_id=user_id,
            links=len(counts),
            new=added,
            shows=sum(counts.values()),
        )
    return added


async def record_paid_subs(session: AsyncSession, user_id: int, links: list[str]) -> int:
    """Insert newly seen paid offer links. Returns how many rows were added."""
    added = 0
    for raw in links:
        link = (raw or "").strip()[:512]
        if not link:
            continue
        exists = await session.execute(
            select(PiarflowPaidSub.id).where(
                PiarflowPaidSub.user_id == user_id,
                PiarflowPaidSub.offer_link == link,
            )
        )
        if exists.scalar_one_or_none() is not None:
            continue
        session.add(PiarflowPaidSub(user_id=user_id, offer_link=link))
        added += 1
    if added:
        await session.flush()
        log.info("piarflow_credited", user_id=user_id, new=added)
    return added


async def record_from_op_result(
    session: AsyncSession, user_id: int, result: OpResult
) -> tuple[int, int]:
    """Persist issued sponsors and credited links from one OP result."""
    issued_links = [s.url for s in result.sponsors if s.url]
    issued = await record_issued_sponsors(session, user_id, issued_links) if issued_links else 0
    paid = await record_paid_subs(session, user_id, result.paid_links) if result.paid_links else 0
    return issued, paid


async def paid_sub_count(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(PiarflowPaidSub).where(PiarflowPaidSub.user_id == user_id)
    )
    return int(result.scalar_one())


async def issued_sub_count(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(PiarflowIssuedSub).where(PiarflowIssuedSub.user_id == user_id)
    )
    return int(result.scalar_one())


async def traffic_stats(session: AsyncSession) -> PiarflowTraffic:
    now = datetime.now(UTC)
    today = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
    d7 = now - timedelta(days=7)
    data = PiarflowTraffic()

    data.issued_total = int(
        (await session.execute(select(func.count()).select_from(PiarflowIssuedSub))).scalar_one() or 0
    )
    data.issued_today = int(
        (
            await session.execute(
                select(func.count())
                .select_from(PiarflowIssuedSub)
                .where(PiarflowIssuedSub.first_shown_at >= today)
            )
        ).scalar_one()
        or 0
    )
    data.issued_7d = int(
        (
            await session.execute(
                select(func.count())
                .select_from(PiarflowIssuedSub)
                .where(PiarflowIssuedSub.first_shown_at >= d7)
            )
        ).scalar_one()
        or 0
    )
    data.shows_total = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(PiarflowIssuedSub.show_count), 0)).select_from(
                    PiarflowIssuedSub
                )
            )
        ).scalar_one()
        or 0
    )
    data.unique_users_issued = int(
        (
            await session.execute(select(func.count(func.distinct(PiarflowIssuedSub.user_id))))
        ).scalar_one()
        or 0
    )

    data.credited_total = int(
        (await session.execute(select(func.count()).select_from(PiarflowPaidSub))).scalar_one() or 0
    )
    data.credited_today = int(
        (
            await session.execute(
                select(func.count())
                .select_from(PiarflowPaidSub)
                .where(PiarflowPaidSub.created_at >= today)
            )
        ).scalar_one()
        or 0
    )
    data.credited_7d = int(
        (
            await session.execute(
                select(func.count())
                .select_from(PiarflowPaidSub)
                .where(PiarflowPaidSub.created_at >= d7)
            )
        ).scalar_one()
        or 0
    )
    data.unique_users_credited = int(
        (await session.execute(select(func.count(func.distinct(PiarflowPaidSub.user_id))))).scalar_one()
        or 0
    )

    data.unsubs_total = int(
        (await session.execute(select(func.count()).select_from(PiarflowUnsub))).scalar_one() or 0
    )
    data.unsubs_today = int(
        (
            await session.execute(
                select(func.count())
                .select_from(PiarflowUnsub)
                .where(PiarflowUnsub.created_at >= today)
            )
        ).scalar_one()
        or 0
    )
    return data


async def list_issued(
    session: AsyncSession, *, limit: int = 8, offset: int = 0
) -> list[PiarflowIssuedSub]:
    result = await session.execute(
        select(PiarflowIssuedSub)
        .order_by(PiarflowIssuedSub.last_shown_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_credited(
    session: AsyncSession, *, limit: int = 8, offset: int = 0
) -> list[PiarflowPaidSub]:
    result = await session.execute(
        select(PiarflowPaidSub).order_by(PiarflowPaidSub.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars().all())


async def count_issued(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(PiarflowIssuedSub))).scalar_one() or 0)


async def count_credited(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(PiarflowPaidSub))).scalar_one() or 0)
