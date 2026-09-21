"""Track PiarFlow resources that were paid (status ``subscribed``) for a user.

Referral activation requires a minimum number of such paid subscriptions so
multi-accounts that only click through unpaid / not_counted tasks do not mint
referral bonuses.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PiarflowPaidSub


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
    return added


async def paid_sub_count(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(PiarflowPaidSub).where(PiarflowPaidSub.user_id == user_id)
    )
    return int(result.scalar_one())
