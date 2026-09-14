from datetime import UTC, datetime

from sqlalchemy import select
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
            first_name=first_name or "",
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
        user.first_name = first_name or user.first_name
        user.language_code = (language_code or user.language_code or "ru")[:8]
        user.is_premium = is_premium
    user.last_action_at = datetime.now(UTC)
    await session.flush()
    return user, created


def require_not_banned(user: User) -> None:
    if user.is_banned:
        raise UserBanned(user.ban_reason or "Аккаунт заблокирован")


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.get(User, telegram_id)


async def list_user_ids(session: AsyncSession, *, only_active: bool = True) -> list[int]:
    stmt = select(User.id)
    if only_active:
        stmt = stmt.where(User.is_banned.is_(False))
    result = await session.execute(stmt)
    return list(result.scalars().all())
