"""Anti-multiaccount («твинки»): device fingerprints collected by the Mini App.

The Mini App posts a fingerprint hash (user agent, screen, GPU/canvas, timezone,
languages, Telegram platform…) together with signed ``initData``. The server adds
the client IP. Two accounts sharing a fingerprint are linked: the later one gets
``twink_of = <first account>`` and — depending on runtime settings — receives no
referral payout and/or cannot withdraw. Admins may whitelist a user (``is_trusted``)
when people legitimately share a device.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import DeviceCheck, User
from app.services import events
from app.services.antifraud import record_event
from app.services.errors import ValidationError

FP_MAX_LEN = 64
SIGNAL_KEYS = (
    "ua",
    "platform",
    "tg_platform",
    "tg_version",
    "languages",
    "timezone",
    "screen",
    "dpr",
    "color_depth",
    "cores",
    "memory",
    "touch",
    "webgl",
    "canvas",
    "fonts",
)


@dataclass(slots=True)
class DeviceVerdict:
    fingerprint: str
    matched_user_ids: list[int]
    twink: bool
    first_time: bool

    @property
    def clean(self) -> bool:
        return not self.twink


def normalize_fingerprint(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not value:
        raise ValidationError("Пустой отпечаток устройства")
    if len(value) > FP_MAX_LEN or any(ch not in "0123456789abcdef" for ch in value):
        # Client sent something unexpected: hash it so storage stays uniform.
        value = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return value


def fingerprint_from_signals(signals: dict[str, Any]) -> str:
    """Server-side fallback hash over the whitelisted signals (stable ordering)."""
    payload = {key: signals.get(key) for key in SIGNAL_KEYS if signals.get(key) not in (None, "")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def clean_signals(signals: Any) -> dict[str, Any]:
    if not isinstance(signals, dict):
        return {}
    out: dict[str, Any] = {}
    for key in SIGNAL_KEYS:
        value = signals.get(key)
        if value is None:
            continue
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        out[key] = text[:512]
    return out


def is_device_ok(user: User, settings: Settings) -> bool:
    """Whether the account passed device verification (or it is not required)."""
    if not settings.device_check_active:
        return True
    return user.device_verified_at is not None or user.is_trusted


def referral_blocked_by_twink(user: User, settings: Settings) -> bool:
    return settings.twink_block_referral and user.is_twink


def withdraw_blocked_by_twink(user: User, settings: Settings) -> bool:
    return settings.twink_block_withdraw and user.is_twink


async def register_device(
    session: AsyncSession,
    *,
    user: User,
    fingerprint: str,
    ip: str | None,
    user_agent: str | None,
    platform: str | None,
    tg_version: str | None,
    signals: dict[str, Any] | None,
    settings: Settings,
) -> DeviceVerdict:
    fp = normalize_fingerprint(fingerprint)
    first_time = user.device_verified_at is None
    matched = await _matching_users(session, user=user, fp=fp, ip=ip, settings=settings)

    session.add(
        DeviceCheck(
            user_id=user.id,
            fp_hash=fp,
            ip=(ip or "")[:64] or None,
            user_agent=(user_agent or "")[:512] or None,
            platform=(platform or "")[:32] or None,
            tg_version=(tg_version or "")[:16] or None,
            signals=clean_signals(signals) or None,
            matched_user_id=matched[0] if matched else None,
        )
    )
    user.device_fp = fp
    user.device_verified_at = datetime.now(UTC)

    twink = False
    if matched and not user.is_trusted:
        if user.twink_of is None:
            user.twink_of = matched[0]
            await record_event(
                session,
                user.id,
                "twink_device",
                f"fp={fp[:12]} ip={ip or '-'} matches={','.join(str(uid) for uid in matched[:5])}",
            )
        twink = True
    await session.flush()
    events.emit(
        session,
        "device_verified",
        user_id=user.id,
        twink=twink,
        matched=matched[:5],
        first_time=first_time,
    )
    return DeviceVerdict(fingerprint=fp, matched_user_ids=matched, twink=twink, first_time=first_time)


async def _matching_users(
    session: AsyncSession,
    *,
    user: User,
    fp: str,
    ip: str | None,
    settings: Settings,
) -> list[int]:
    """Other accounts that used the same fingerprint (optionally also the same IP)."""
    stmt = (
        select(DeviceCheck.user_id, func.max(DeviceCheck.created_at))
        .where(DeviceCheck.fp_hash == fp, DeviceCheck.user_id != user.id)
        .group_by(DeviceCheck.user_id)
    )
    if settings.twink_require_ip_match:
        if not ip:
            return []
        since = datetime.now(UTC) - timedelta(days=max(settings.twink_ip_window_days, 1))
        stmt = stmt.where(DeviceCheck.ip == ip, DeviceCheck.created_at >= since)
    rows = (await session.execute(stmt)).all()
    candidates = sorted(rows, key=lambda row: (row[1] or datetime.min.replace(tzinfo=UTC), row[0]))
    out: list[int] = []
    for uid, _seen in candidates:
        other = await session.get(User, int(uid))
        if other is None or other.is_trusted:
            continue
        out.append(int(uid))
    return out


async def linked_accounts(session: AsyncSession, user: User, *, limit: int = 10) -> list[User]:
    """Accounts sharing a fingerprint with ``user`` (both directions)."""
    if not user.device_fp:
        return []
    result = await session.execute(
        select(User)
        .where(User.device_fp == user.device_fp, User.id != user.id)
        .order_by(User.created_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def set_trusted(session: AsyncSession, user: User, trusted: bool) -> None:
    user.is_trusted = trusted
    if trusted:
        user.twink_of = None
    await session.flush()


async def clusters(session: AsyncSession, *, limit: int = 15) -> list[tuple[str, int, list[User]]]:
    """Fingerprints used by more than one account, biggest clusters first."""
    stmt = (
        select(User.device_fp, func.count())
        .where(User.device_fp.is_not(None))
        .group_by(User.device_fp)
        .having(func.count() > 1)
        .order_by(func.count().desc())
        .limit(limit)
    )
    out: list[tuple[str, int, list[User]]] = []
    for fp, count in (await session.execute(stmt)).all():
        members = (
            await session.execute(select(User).where(User.device_fp == fp).order_by(User.created_at).limit(8))
        ).scalars()
        out.append((str(fp), int(count), list(members)))
    return out


async def stats(session: AsyncSession) -> dict[str, int]:
    verified = await session.execute(
        select(func.count()).select_from(User).where(User.device_verified_at.is_not(None))
    )
    twinks = await session.execute(
        select(func.count()).select_from(User).where(User.twink_of.is_not(None), User.is_trusted.is_(False))
    )
    trusted = await session.execute(select(func.count()).select_from(User).where(User.is_trusted.is_(True)))
    return {
        "verified": int(verified.scalar_one()),
        "twinks": int(twinks.scalar_one()),
        "trusted": int(trusted.scalar_one()),
    }
