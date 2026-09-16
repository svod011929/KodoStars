from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LedgerKind, User
from app.services import ledger
from app.services.errors import UserBanned


async def upsert_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str,
    language_code: str | None,
    is_premium: bool,
    settings: Settings,
) -> tuple[User, bool]:
    user = await session.get(User, telegram_id)
    created = user is None
    if user is None:
        user = User(
            id=telegram_id,
            username=username,
            first_name=(first_name or "")[:128],
            language_code=(language_code or "ru")[:8],
            is_premium=is_premium,
        )
        session.add(user)
        await session.flush()
        if settings.signup_bonus > 0:
            await ledger.credit(
                session,
                user_id=user.id,
                amount=settings.signup_bonus,
                kind=LedgerKind.SIGNUP,
                reference="signup",
            )
    else:
        user.username = username
        user.first_name = (first_name or user.first_name)[:128]
        user.language_code = (language_code or user.language_code or "ru")[:8]
        user.is_premium = is_premium
        if user.blocked_bot_at is not None:
            # The user is talking to us again — they unblocked the bot.
            user.blocked_bot_at = None
    user.last_action_at = datetime.now(UTC)
    await session.flush()
    return user, created


def mark_started(user: User) -> bool:
    """Record the first real ``/start``. Returns True if this was the first one."""
    if user.started_at is not None:
        return False
    user.started_at = datetime.now(UTC)
    return True


def require_not_banned(user: User) -> None:
    if user.is_banned:
        raise UserBanned(user.ban_reason or "Аккаунт заблокирован")


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.get(User, telegram_id)


async def find_user(session: AsyncSession, query: str) -> User | None:
    """Lookup by numeric id or ``@username`` / ``username`` (case-insensitive)."""
    raw = query.strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        return await session.get(User, int(raw))
    username = raw.lstrip("@").strip()
    if not username:
        return None
    result = await session.execute(select(User).where(func.lower(User.username) == username.lower()).limit(1))
    return result.scalar_one_or_none()


async def set_blocked_bot(session: AsyncSession, user_id: int, blocked: bool) -> None:
    user = await session.get(User, user_id)
    if user is None:
        return
    user.blocked_bot_at = datetime.now(UTC) if blocked else None
    await session.flush()


async def list_user_ids(
    session: AsyncSession,
    *,
    only_active: bool = True,
    exclude_blocked: bool = True,
) -> list[int]:
    stmt = select(User.id).order_by(User.id)
    if only_active:
        stmt = stmt.where(User.is_banned.is_(False))
    if exclude_blocked:
        stmt = stmt.where(User.blocked_bot_at.is_(None))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def audience_ids(session: AsyncSession, audience: str) -> list[int]:
    """User ids for a broadcast audience; banned and bot-blocking users are excluded."""
    stmt = select(User.id).where(User.is_banned.is_(False), User.blocked_bot_at.is_(None))
    if audience == "active_7d":
        since = datetime.now(UTC) - timedelta(days=7)
        stmt = stmt.where(User.last_action_at.is_not(None), User.last_action_at >= since)
    elif audience == "activated":
        stmt = stmt.where(User.referral_activated.is_(True))
    result = await session.execute(stmt.order_by(User.id))
    return list(result.scalars().all())


async def recent_users(session: AsyncSession, *, limit: int = 10, offset: int = 0) -> list[User]:
    result = await session.execute(
        select(User).order_by(User.created_at.desc(), User.id.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars().all())


async def count_users(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(User))).scalar_one())


async def search_users(session: AsyncSession, query: str, *, limit: int = 10) -> list[User]:
    raw = query.strip().lstrip("@")
    if not raw:
        return []
    pattern = f"%{raw.lower()}%"
    conditions = [
        func.lower(func.coalesce(User.username, "")).like(pattern),
        func.lower(User.first_name).like(pattern),
    ]
    if raw.isdigit():
        conditions.append(User.id == int(raw))
    result = await session.execute(select(User).where(or_(*conditions)).limit(limit))
    return list(result.scalars().all())
