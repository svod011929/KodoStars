from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import FraudEvent, User
from app.services.errors import CooldownActive, UserBanned


async def record_event(
    session: AsyncSession,
    user_id: int,
    kind: str,
    detail: str = "",
) -> FraudEvent:
    event = FraudEvent(user_id=user_id, kind=kind, detail=detail)
    session.add(event)
    await session.flush()
    return event


def ensure_not_banned(user: User) -> None:
    if user.is_banned:
        raise UserBanned(user.ban_reason or "Аккаунт заблокирован")


def ensure_action_cooldown(user: User, settings: Settings) -> None:
    if not user.last_action_at or settings.claim_cooldown_seconds <= 0:
        return
    last = user.last_action_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    elapsed = datetime.now(UTC) - last
    wait = timedelta(seconds=settings.claim_cooldown_seconds)
    if elapsed < wait:
        raise CooldownActive("Слишком часто. Подождите пару секунд.")


async def bump_activity(session: AsyncSession, user: User, points: int = 1) -> None:
    user.activity_score += max(points, 0)
    user.last_action_at = datetime.now(UTC)
    await session.flush()


async def set_ban(
    session: AsyncSession,
    user: User,
    *,
    banned: bool,
    reason: str,
    admin_id: int,
) -> None:
    user.is_banned = banned
    user.ban_reason = reason if banned else None
    await record_event(
        session,
        user.id,
        "ban" if banned else "unban",
        f"admin={admin_id}; {reason}",
    )
    await session.flush()
