from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.utils import parse_id, safe_answer, safe_edit
from app.config import Settings
from app.db.models import BoostProduct, Task, User
from app.services import daily
from app.services import tasks as task_service
from app.services.boosts import active_boosts, get_product, list_products
from app.services.boosts import describe as boost_detail
from app.services.channels import is_member
from app.services.errors import AlreadyClaimed, EconomyError

router = Router(name="earn")


# --- daily --------------------------------------------------------------------------


@router.callback_query(F.data == "menu:daily")
async def menu_daily(call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings) -> None:
    preview = await daily.preview(session, user=db_user, settings=settings)
    await safe_answer(call)
    await safe_edit(
        call.message, texts.daily_screen(preview, settings), keyboards.daily_menu(preview.claimed_today)
    )


@router.callback_query(F.data == "daily:claim")
async def daily_claim(call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings) -> None:
    try:
        claim = await daily.claim_daily(session, user=db_user, settings=settings)
    except AlreadyClaimed:
        preview = await daily.preview(session, user=db_user, settings=settings)
        await safe_answer(call, texts.daily_wait(), alert=True)
        await safe_edit(call.message, texts.daily_screen(preview, settings), keyboards.daily_menu(True))
        return
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call, f"+{claim.amount} ⭐")
    await safe_edit(call.message, texts.daily_ok(claim.amount, claim.streak), keyboards.daily_menu(True))


# --- tasks --------------------------------------------------------------------------


async def _tasks_view(session: AsyncSession, user: User):
    items = await task_service.list_tasks(session)
    done = await task_service.completed_task_ids(session, user.id)
    return texts.tasks_header(len(done & {t.id for t in items}), len(items)), keyboards.tasks_keyboard(
        items, done
    )


@router.callback_query(F.data == "menu:tasks")
async def menu_tasks(call: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _tasks_view(session, db_user)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data.startswith("task:view:"))
async def task_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    task = await session.get(Task, parse_id(call.data))
    if task is None or not task.is_active:
        await safe_answer(call, "Задание недоступно", alert=True)
        return
    done = task.id in await task_service.completed_task_ids(session, db_user.id)
    await safe_answer(call)
    await safe_edit(call.message, texts.task_card(task, done), keyboards.task_card(task, done))


@router.callback_query(F.data.startswith("task:do:"))
async def task_do(
    call: CallbackQuery, session: AsyncSession, db_user: User, settings: Settings, bot: Bot
) -> None:
    task_id = parse_id(call.data)

    async def _checker(channel: str) -> bool | None:
        return await is_member(bot, db_user.id, channel)

    try:
        _, amount = await task_service.claim_task(
            session, user=db_user, task_id=task_id, settings=settings, membership_checker=_checker
        )
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    await safe_answer(call, f"Задание выполнено: +{amount} ⭐", alert=True)
    task = await session.get(Task, task_id)
    if task is not None:
        await safe_edit(call.message, texts.task_card(task, True), keyboards.task_card(task, True))


# --- boosts -------------------------------------------------------------------------


async def _boost_titles(session: AsyncSession, boosts) -> dict[int, str]:
    titles: dict[int, str] = {}
    for boost in boosts:
        product = await session.get(BoostProduct, boost.product_id)
        titles[boost.product_id] = product.title if product else "Буст"
    return titles


@router.callback_query(F.data == "menu:boosts")
async def menu_boosts(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    products = await list_products(session)
    active = await active_boosts(session, db_user.id)
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.boosts_header(active, await _boost_titles(session, active)),
        keyboards.boosts_keyboard(products),
    )


@router.callback_query(F.data.startswith("boost:view:"))
async def boost_view(call: CallbackQuery, session: AsyncSession) -> None:
    product = await get_product(session, parse_id(call.data))
    if product is None or not product.is_active:
        await safe_answer(call, "Буст недоступен", alert=True)
        return
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.boost_card(
            product.title, product.description, product.xtr_price, boost_detail(product).capitalize()
        ),
        keyboards.boost_card(product),
    )


@router.callback_query(F.data.startswith("boost:buy:"))
async def boost_buy(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    product = await get_product(session, parse_id(call.data))
    if product is None or not product.is_active:
        await safe_answer(call, "Буст недоступен", alert=True)
        return
    await safe_answer(call)
    if call.message:
        await call.message.answer_invoice(
            title=product.title[:32],
            description=(product.description or boost_detail(product))[:255],
            payload=f"boost:{product.id}:{db_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label=product.title[:32], amount=product.xtr_price)],
        )
