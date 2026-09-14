from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.config import Settings
from app.db.models import User
from app.services import ledger, referrals
from app.services.boosts import active_multiplier_bp
from app.services.levels import info_for_xp


async def render_home(
    session: AsyncSession,
    user: User,
    settings: Settings,
    bot_username: str,
) -> tuple[str, InlineKeyboardMarkup]:
    balance = await ledger.get_balance(session, user.id)
    boost_bp = await active_multiplier_bp(session, user.id)
    text = texts.home(user, balance, info_for_xp(user.xp), boost_bp, bot_username)
    return text, keyboards.main_menu(user.id in settings.admin_ids)
