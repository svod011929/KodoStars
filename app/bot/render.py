from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.utils import fmt_dt
from app.config import Settings
from app.db.models import User
from app.services import ledger, withdrawals
from app.services.boosts import active_boosts
from app.services.devices import is_device_ok
from app.services.levels import info_for_xp
from app.services.referrals import referral_link

VERIFY_PATH = "verify"


def device_url_for(user: User, settings: Settings) -> str | None:
    """Mini App URL when the user still has to pass device verification."""
    if not settings.device_check_active or is_device_ok(user, settings):
        return None
    return settings.web_url(VERIFY_PATH)


async def render_home(
    session: AsyncSession,
    user: User,
    *,
    bot_username: str,
    is_admin: bool,
    settings: Settings,
) -> tuple[str, InlineKeyboardMarkup]:
    balance = await ledger.get_balance(session, user.id)
    held = await withdrawals.held_total(session, user.id)
    boosts = await active_boosts(session, user.id)
    boost_bp = max([100, *[boost.multiplier_bp for boost in boosts]])
    boost_until = None
    if boosts:
        best = max(boosts, key=lambda item: item.multiplier_bp)
        boost_until = fmt_dt(best.expires_at)
    device_url = device_url_for(user, settings)
    notice = ""
    if device_url:
        notice = texts.device_notice(settings.device_check_for_withdraw)
    elif user.is_twink and settings.twink_block_referral:
        notice = texts.device_twink_notice()
    text = texts.home(
        user,
        balance,
        held,
        info_for_xp(user.xp),
        boost_bp,
        boost_until,
        referral_link(bot_username, user.id),
        device_notice=notice,
        l1_bonus=settings.referral_l1_bonus,
    )
    return text, keyboards.main_menu(
        is_admin, device_url=device_url, l1_bonus=settings.referral_l1_bonus
    )
