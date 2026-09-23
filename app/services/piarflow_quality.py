"""Track OP sponsors that were issued and those that were paid (subscribed).

Rows live in the original PiarFlow tables and are split by ``provider``
(``piarflow``, ``tgrass``). Referral activation still counts PiarFlow paid
subs only. Admin traffic stats compare issued inventory vs credited sales
for every provider in the cascade.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PiarflowIssuedSub, PiarflowPaidSub, PiarflowUnsub, TgrassUnsub
from app.op.base import CASCADE, OpResult

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


async def record_issued_sponsors(
    session: AsyncSession,
    user_id: int,
    links: list[str],
    *,
    provider: str = "piarflow",
) -> int:
    """Upsert issued offer links for one provider. Returns how many *new* rows were added."""
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
                PiarflowIssuedSub.provider == provider,
                PiarflowIssuedSub.user_id == user_id,
                PiarflowIssuedSub.offer_link == link,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            session.add(
                PiarflowIssuedSub(
                    provider=provider,
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
            provider=provider,
            user_id=user_id,
            links=len(counts),
            new=added,
            shows=sum(counts.values()),
        )
    return added


async def record_paid_subs(
    session: AsyncSession,
    user_id: int,
    links: list[str],
    *,
    provider: str = "piarflow",
) -> int:
    """Insert newly seen paid offer links for one provider. Returns how many rows were added."""
    added = 0
    for raw in links:
        link = (raw or "").strip()[:512]
        if not link:
            continue
        exists = await session.execute(
            select(PiarflowPaidSub.id).where(
                PiarflowPaidSub.provider == provider,
                PiarflowPaidSub.user_id == user_id,
                PiarflowPaidSub.offer_link == link,
            )
        )
        if exists.scalar_one_or_none() is not None:
            continue
        session.add(PiarflowPaidSub(provider=provider, user_id=user_id, offer_link=link))
        added += 1
    if added:
        await session.flush()
        log.info("piarflow_credited", provider=provider, user_id=user_id, new=added)
    return added


async def record_from_op_result(
    session: AsyncSession, user_id: int, result: OpResult
) -> tuple[int, int]:
    """Persist issued sponsors and credited links from one provider result.

    The final gate result (``provider="gate"``) is ignored: each adapter is
    recorded on its own, otherwise paid links would be stored twice.
    """
    if result.skipped or result.fail_open or result.provider == "gate" or not result.provider:
        return 0, 0
    provider = result.provider
    issued_links = [s.url for s in result.sponsors if s.url]
    issued = (
        await record_issued_sponsors(session, user_id, issued_links, provider=provider)
        if issued_links
        else 0
    )
    paid = (
        await record_paid_subs(session, user_id, result.paid_links, provider=provider)
        if result.paid_links
        else 0
    )
    return issued, paid


async def paid_sub_count(session: AsyncSession, user_id: int) -> int:
    """Paid PiarFlow subs only. Referral activation must not count other providers."""
    result = await session.execute(
        select(func.count())
        .select_from(PiarflowPaidSub)
        .where(
            PiarflowPaidSub.user_id == user_id,
            PiarflowPaidSub.provider == "piarflow",
        )
    )
    return int(result.scalar_one())


async def issued_sub_count(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(PiarflowIssuedSub).where(PiarflowIssuedSub.user_id == user_id)
    )
    return int(result.scalar_one())


async def _count(session: AsyncSession, model, *criteria) -> int:
    stmt = select(func.count()).select_from(model)
    if criteria:
        stmt = stmt.where(*criteria)
    return int((await session.execute(stmt)).scalar_one() or 0)


def _unsub_models(provider: str | None) -> tuple[type, ...]:
    if provider == "tgrass":
        return (TgrassUnsub,)
    if provider == "piarflow":
        return (PiarflowUnsub,)
    if provider is None:
        return (PiarflowUnsub, TgrassUnsub)
    return ()


async def traffic_stats(session: AsyncSession, provider: str | None = None) -> PiarflowTraffic:
    """Inventory vs credited sales. ``provider=None`` sums every provider."""
    now = datetime.now(UTC)
    today = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
    d7 = now - timedelta(days=7)
    issued_where = (PiarflowIssuedSub.provider == provider,) if provider else ()
    paid_where = (PiarflowPaidSub.provider == provider,) if provider else ()
    data = PiarflowTraffic()

    data.issued_total = await _count(session, PiarflowIssuedSub, *issued_where)
    data.issued_today = await _count(
        session, PiarflowIssuedSub, *issued_where, PiarflowIssuedSub.first_shown_at >= today
    )
    data.issued_7d = await _count(
        session, PiarflowIssuedSub, *issued_where, PiarflowIssuedSub.first_shown_at >= d7
    )
    shows = select(func.coalesce(func.sum(PiarflowIssuedSub.show_count), 0)).select_from(PiarflowIssuedSub)
    if issued_where:
        shows = shows.where(*issued_where)
    data.shows_total = int((await session.execute(shows)).scalar_one() or 0)
    distinct_issued = select(func.count(func.distinct(PiarflowIssuedSub.user_id)))
    if issued_where:
        distinct_issued = distinct_issued.where(*issued_where)
    data.unique_users_issued = int((await session.execute(distinct_issued)).scalar_one() or 0)

    data.credited_total = await _count(session, PiarflowPaidSub, *paid_where)
    data.credited_today = await _count(
        session, PiarflowPaidSub, *paid_where, PiarflowPaidSub.created_at >= today
    )
    data.credited_7d = await _count(
        session, PiarflowPaidSub, *paid_where, PiarflowPaidSub.created_at >= d7
    )
    distinct_paid = select(func.count(func.distinct(PiarflowPaidSub.user_id)))
    if paid_where:
        distinct_paid = distinct_paid.where(*paid_where)
    data.unique_users_credited = int((await session.execute(distinct_paid)).scalar_one() or 0)

    unsubs_total = 0
    unsubs_today = 0
    for model in _unsub_models(provider):
        unsubs_total += await _count(session, model)
        unsubs_today += await _count(session, model, model.created_at >= today)
    data.unsubs_total = unsubs_total
    data.unsubs_today = unsubs_today
    return data


async def traffic_by_provider(session: AsyncSession) -> list[tuple[str, PiarflowTraffic]]:
    """One stats block per OP provider, in cascade order."""
    return [(name, await traffic_stats(session, provider=name)) for name in CASCADE]


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
