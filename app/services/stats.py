from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry, User, Withdrawal, WithdrawalStatus


async def dashboard(session: AsyncSession) -> dict[str, int]:
    users = await session.execute(select(func.count()).select_from(User))
    banned = await session.execute(
        select(func.count()).select_from(User).where(User.is_banned.is_(True))
    )
    stars = await session.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.amount > 0)
    )
    pending = await session.execute(
        select(func.count())
        .select_from(Withdrawal)
        .where(Withdrawal.status == WithdrawalStatus.PENDING.value)
    )
    approved = await session.execute(
        select(func.count())
        .select_from(Withdrawal)
        .where(Withdrawal.status == WithdrawalStatus.APPROVED_MANUAL.value)
    )
    sent = await session.execute(
        select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(
            Withdrawal.status == WithdrawalStatus.SENT.value
        )
    )
    return {
        "users": int(users.scalar_one()),
        "banned": int(banned.scalar_one()),
        "stars_credited": int(stars.scalar_one()),
        "withdraw_pending": int(pending.scalar_one()),
        "withdraw_approved": int(approved.scalar_one()),
        "withdraw_sent_stars": int(sent.scalar_one()),
    }
