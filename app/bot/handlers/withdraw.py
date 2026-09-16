from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.render import device_url_for
from app.bot.utils import button, parse_id, safe_answer, safe_edit
from app.config import Settings
from app.db.models import User, Withdrawal
from app.services import gifts, ledger, withdrawals
from app.services.errors import EconomyError
from app.services.gifts import GIFTS_PER_PAGE, GiftOffer

router = Router(name="withdraw")


async def _load_offers(
    bot: Bot, user: User, settings: Settings, balance: int
) -> tuple[list[GiftOffer], bool]:
    try:
        offers = await gifts.list_affordable(
            bot, balance=balance, settings=settings, is_premium=bool(user.is_premium)
        )
        return offers, False
    except TelegramAPIError:
        return [], True


async def _home_view(
    session: AsyncSession,
    user: User,
    settings: Settings,
    bot: Bot,
    *,
    page: int = 0,
):
    balance = await ledger.get_balance(session, user.id)
    held = await withdrawals.held_total(session, user.id)
    open_request = await withdrawals.open_withdrawal(session, user.id)
    device_url = device_url_for(user, settings) if settings.device_check_for_withdraw else None
    offers: list[GiftOffer] = []
    catalog_error = False
    can_pick = settings.withdraw_enabled and not user.is_banned and open_request is None and not device_url
    if can_pick:
        offers, catalog_error = await _load_offers(bot, user, settings, balance)
    text = texts.withdraw_home(
        balance,
        held,
        settings,
        open_request,
        offers_count=len(offers),
        catalog_error=catalog_error,
        can_pick=can_pick,
    )
    if device_url:
        text += "\n\n" + texts.device_notice(for_withdraw=True)
    markup = keyboards.withdraw_keyboard(
        offers,
        enabled=settings.withdraw_enabled and not user.is_banned,
        has_open=open_request is not None,
        page=page,
        per_page=GIFTS_PER_PAGE,
        device_url=device_url,
        catalog_error=catalog_error,
    )
    return text, markup


@router.callback_query(F.data == "menu:withdraw")
async def menu_withdraw(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
    state: FSMContext,
) -> None:
    await state.clear()
    text, markup = await _home_view(session, db_user, settings, call.bot)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.startswith("wd:page:"))
async def withdraw_page(
    call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings
) -> None:
    page = max(parse_id(call.data), 0)
    text, markup = await _home_view(session, db_user, settings, call.bot, page=page)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


async def _apply_gift(session: AsyncSession, user: User, offer: GiftOffer, settings: Settings) -> str:
    try:
        wd = await withdrawals.apply(
            session,
            user=user,
            amount=offer.star_count,
            settings=settings,
            gift_id=offer.id,
            gift_emoji=offer.emoji,
        )
    except EconomyError as exc:
        return f"⚠️ {exc.message}"
    return texts.withdraw_created(wd)


@router.callback_query(F.data.startswith("wd:g:"))
async def withdraw_gift(
    call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings
) -> None:
    gift_id = (call.data or "").split(":", 2)[-1]
    offer = await gifts.resolve_offer(call.bot, gift_id)
    if offer is None:
        await safe_answer(call, "Этот подарок больше недоступен. Обновите список.", alert=True)
        text, markup = await _home_view(session, db_user, settings, call.bot)
        await safe_edit(call.message, text, markup)
        return
    if offer.is_premium and not db_user.is_premium:
        await safe_answer(call, "Этот подарок доступен только Premium-пользователям", alert=True)
        return
    text = await _apply_gift(session, db_user, offer, settings)
    await safe_answer(call)
    await safe_edit(call.message, text, keyboards.back_home([button("📄 Мои заявки", "wd:list")]))


@router.callback_query(F.data == "wd:list")
async def withdraw_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    items = await withdrawals.list_user_withdrawals(session, db_user.id, limit=10)
    await safe_answer(call)
    await safe_edit(call.message, texts.withdraw_list(items), keyboards.withdraw_list_menu(items))


@router.callback_query(F.data.startswith("wd:cancel:"))
async def withdraw_cancel(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    wd = await session.get(Withdrawal, parse_id(call.data))
    if wd is None:
        await safe_answer(call, "Заявка не найдена", alert=True)
        return
    try:
        await withdrawals.cancel(session, withdrawal=wd, user=db_user)
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call, "Заявка отменена, Stars возвращены", alert=True)
    items = await withdrawals.list_user_withdrawals(session, db_user.id, limit=10)
    await safe_edit(call.message, texts.withdraw_list(items), keyboards.withdraw_list_menu(items))
