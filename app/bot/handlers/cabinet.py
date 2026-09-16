from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.render import render_home
from app.bot.utils import PAGE_SIZE, button, parse_id, safe_answer, safe_edit
from app.config import Settings
from app.db.models import BoostProduct, User
from app.services import leaderboard, ledger, referrals, withdrawals
from app.services.boosts import active_boosts
from app.services.levels import info_for_xp
from app.services.referrals import referral_link

router = Router(name="cabinet")


async def profile_view(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup]:
    balance = await ledger.get_balance(session, user.id)
    held = await withdrawals.held_total(session, user.id)
    refs = await referrals.referral_stats(session, user.id)
    earned = await referrals.referral_earnings(session, user.id)
    boosts = await active_boosts(session, user.id)
    titles: dict[int, str] = {}
    for boost in boosts:
        product = await session.get(BoostProduct, boost.product_id)
        titles[boost.product_id] = product.title if product else "Буст"
    text = texts.profile(user, balance, held, info_for_xp(user.xp), refs, earned, boosts, titles)
    return text, keyboards.profile_menu()


@router.callback_query(F.data == "menu:home")
async def menu_home(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    state: FSMContext,
    bot_username: str,
    is_admin: bool,
    settings: Settings,
) -> None:
    await state.clear()
    text, markup = await render_home(
        session, db_user, bot_username=bot_username, is_admin=is_admin, settings=settings
    )
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "menu:profile")
async def menu_profile(call: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await profile_view(session, db_user)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.startswith("menu:history:"))
async def menu_history(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    page = parse_id(call.data)
    total = await ledger.count_entries(session, db_user.id)
    entries = await ledger.history(session, db_user.id, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.history(entries, page, total, PAGE_SIZE),
        keyboards.history_menu(page, total),
    )


@router.callback_query(F.data == "menu:refs")
async def menu_refs(
    call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings, bot_username: str
) -> None:
    link = referral_link(bot_username, db_user.id)
    stats = await referrals.referral_stats(session, db_user.id)
    activated = await referrals.activated_invite_count(session, db_user.id)
    earned = await referrals.referral_earnings(session, db_user.id)
    rank = await leaderboard.user_rank_by_referrals(session, db_user.id)
    recent = await referrals.list_referrals(session, db_user.id, level=1, limit=5)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.referrals(db_user, link, stats, activated, earned, rank, settings, recent),
        keyboards.referrals_menu(link, texts.share_text(link, settings.signup_bonus)),
    )


@router.callback_query(F.data.startswith("menu:top:"))
async def menu_top(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    mode = (call.data or "").split(":")[-1]
    rows_refs = await leaderboard.top_referrers(session, limit=10)
    rows_earn = await leaderboard.top_earners(session, limit=10, days=7) if mode == "earn" else []
    my_rank = await leaderboard.user_rank_by_referrals(session, db_user.id)
    await safe_answer(call)
    await safe_edit(call.message, texts.top(rows_refs, rows_earn, mode, my_rank), keyboards.top_menu(mode))


@router.callback_query(F.data == "menu:help")
async def menu_help(call: CallbackQuery, settings: Settings, is_admin: bool) -> None:
    await safe_answer(call)
    await safe_edit(
        call.message, texts.help_text(settings, is_admin), keyboards.help_menu(settings.support_contact)
    )


@router.callback_query(F.data == "menu:terms")
async def menu_terms(call: CallbackQuery, settings: Settings) -> None:
    await safe_answer(call)
    await safe_edit(
        call.message, texts.terms(settings), keyboards.back_home([button("❓ Помощь", "menu:help")])
    )
