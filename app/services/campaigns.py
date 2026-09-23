"""Traffic campaign links: ``?start=c_CODE`` / ``utm_CODE``.

Every /start with that payload is a click. Distinct telegram ids are users.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, CampaignHit
from app.services.errors import ValidationError

_CODE_RE = re.compile(r"^[A-Z0-9_-]{2,32}$")


def normalize_code(raw: str) -> str:
    code = raw.strip().upper().replace(" ", "")
    if code.startswith("UTM_"):
        code = code[4:]
    elif code.startswith("C_"):
        code = code[2:]
    return code


def parse_campaign_payload(payload: str | None) -> str | None:
    """``c_SUMMER`` / ``utm_summer`` → code, else None (refs and promos stay untouched)."""
    if not payload:
        return None
    raw = payload.strip()
    lower = raw.lower()
    if lower.startswith(("utm_", "c_")):
        code = normalize_code(raw)
    else:
        return None
    if not _CODE_RE.match(code):
        return None
    return code


def campaign_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username.lstrip('@')}?start=c_{normalize_code(code)}"


async def create_campaign(session: AsyncSession, code: str) -> Campaign:
    code = normalize_code(code)
    if not _CODE_RE.match(code):
        raise ValidationError("Код: 2–32 символа, латиница/цифры/_/-")
    existing = await session.execute(select(Campaign).where(Campaign.code == code))
    found = existing.scalar_one_or_none()
    if found is not None:
        return found
    row = Campaign(code=code, title=code)
    session.add(row)
    await session.flush()
    return row


async def record_hit(
    session: AsyncSession,
    *,
    code: str,
    user_id: int,
    is_new: bool,
) -> Campaign:
    campaign = await create_campaign(session, code)
    session.add(CampaignHit(campaign_id=campaign.id, user_id=user_id, is_new=is_new))
    await session.flush()
    return campaign


async def list_campaigns(session: AsyncSession, *, limit: int = 15) -> list[Campaign]:
    result = await session.execute(select(Campaign).order_by(Campaign.id.desc()).limit(limit))
    return list(result.scalars().all())


@dataclass(slots=True, frozen=True)
class CampaignStats:
    clicks_day: int
    clicks_week: int
    clicks_all: int
    users_day: int
    users_week: int
    users_all: int


async def campaign_stats(session: AsyncSession, campaign_id: int) -> CampaignStats:
    now = datetime.now(UTC)
    day = now - timedelta(days=1)
    week = now - timedelta(days=7)

    async def window(since: datetime | None) -> tuple[int, int]:
        stmt = select(func.count(), func.count(func.distinct(CampaignHit.user_id))).where(
            CampaignHit.campaign_id == campaign_id
        )
        if since is not None:
            stmt = stmt.where(CampaignHit.created_at >= since)
        clicks, users = (await session.execute(stmt)).one()
        return int(clicks or 0), int(users or 0)

    clicks_all, users_all = await window(None)
    clicks_week, users_week = await window(week)
    clicks_day, users_day = await window(day)
    return CampaignStats(
        clicks_day=clicks_day,
        clicks_week=clicks_week,
        clicks_all=clicks_all,
        users_day=users_day,
        users_week=users_week,
        users_all=users_all,
    )
