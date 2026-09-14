from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.config import Settings
from app.db.models import User
from app.services import tasks as task_service
from app.services.boosts import get_product, list_products
from app.services.daily import claim_daily
from app.services.errors import AlreadyClaimed, CooldownActive, EconomyError, UserBanned

router = Router(name="earn")


@router.callback_query(F.data == "menu:daily")
async def menu_daily(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    try:
        claim = await claim_daily(session, user=db_user, settings=settings)
        text = texts.daily_ok(claim.amount, claim.streak)
    except AlreadyClaimed:
        text = texts.daily_wait()
    except (CooldownActive, UserBanned, EconomyError) as exc:
        text = exc.message
    await call.answer()
    if call.message:
        await call.message.edit_text(text, reply_markup=keyboards.back_home())


@router.callback_query(F.data == "menu:tasks")
async def menu_tasks(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
) -> None:
    items = await task_service.list_tasks(session)
    done = await task_service.completed_task_ids(session, db_user.id)
    await call.answer()
    if call.message:
        await call.message.edit_text(
            texts.tasks_header(),
            reply_markup=keyboards.tasks_keyboard(items, done),
        )


@router.callback_query(F.data.startswith("task:do:"))
async def task_do(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    task_id = int((call.data or "0").split(":")[-1])
    try:
        await task_service.claim_task(
            session, user=db_user, task_id=task_id, settings=settings
        )
        await call.answer("Задание засчитано", show_alert=True)
    except (AlreadyClaimed, EconomyError, CooldownActive, UserBanned) as exc:
        await call.answer(exc.message, show_alert=True)
        return
    items = await task_service.list_tasks(session)
    done = await task_service.completed_task_ids(session, db_user.id)
    if call.message:
        await call.message.edit_text(
            texts.tasks_header(),
            reply_markup=keyboards.tasks_keyboard(items, done),
        )


@router.callback_query(F.data == "menu:boosts")
async def menu_boosts(call: CallbackQuery, session: AsyncSession) -> None:
    products = await list_products(session)
    await call.answer()
    if call.message:
        await call.message.edit_text(
            texts.boosts_header(),
            reply_markup=keyboards.boosts_keyboard(products),
        )


@router.callback_query(F.data.startswith("boost:buy:"))
async def boost_buy(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
) -> None:
    product_id = int((call.data or "0").split(":")[-1])
    product = await get_product(session, product_id)
    if product is None or not product.is_active:
        await call.answer("Буст недоступен", show_alert=True)
        return
    await call.answer()
    if call.message:
        await call.message.answer_invoice(
            title=product.title,
            description=product.description,
            payload=f"boost:{product.id}:{db_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label="XTR", amount=product.xtr_price)],
        )
