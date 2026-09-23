"""Приветки and traffic-campaign links."""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin.states import AdminFSM
from app.bot.utils import button, h, markup, parse_id, safe_answer, safe_edit
from app.db.models import Greeting
from app.services import campaigns as camp_service
from app.services import greetings as greet_service
from app.services.campaigns import CampaignStats
from app.services.errors import EconomyError

router = Router(name="admin.traffic")


def _back_catalog() -> InlineKeyboardMarkup:
    return markup([button("В каталог", "admin:catalog", icon="back")])


def _greet_list_kb(rows: list[Greeting]) -> InlineKeyboardMarkup:
    buttons = [[button("Новая приветка", "admin:greet:new", icon="plus")]]
    for row in rows[:12]:
        icon = "ok_green" if row.is_active else "off"
        buttons.append(
            [
                button(f"#{row.id} · {row.shows}", f"admin:greet:tg:{row.id}", icon=icon),
                button("Удалить", f"admin:greet:del:{row.id}", icon="trash"),
            ]
        )
    buttons.append([button("В каталог", "admin:catalog", icon="back")])
    return markup(*buttons)


def _greet_text(rows: list[Greeting]) -> str:
    lines = [
        "👋 <b>Приветки</b>",
        "",
        "Показываются по кругу после входа в бот (не на стене ОП).",
        "Меньше показов — раньше в очереди.",
        "",
    ]
    if not rows:
        lines.append("Пока пусто.")
    for row in rows[:12]:
        state = "вкл" if row.is_active else "выкл"
        preview = row.body.replace("\n", " ")[:80]
        lines.append(f"#{row.id} · {state} · показов {row.shows}\n<i>{h(preview)}</i>")
    return "\n".join(lines)


@router.callback_query(F.data == "admin:greet")
async def greet_home(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    rows = await greet_service.list_greetings(session)
    await safe_answer(call)
    await safe_edit(call.message, _greet_text(rows), _greet_list_kb(rows))


@router.callback_query(F.data == "admin:greet:new")
async def greet_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.greeting_body)
    await safe_answer(call)
    await safe_edit(
        call.message,
        "Отправьте текст приветки. Можно с форматированием Telegram.",
        markup([button("Отмена", "admin:greet", icon="cross")]),
    )


@router.message(StateFilter(AdminFSM.greeting_body))
async def greet_body(message: Message, state: FSMContext) -> None:
    raw = (message.html_text or message.text or "").strip()
    if not raw or raw.startswith("/"):
        await state.clear()
        return
    await state.update_data(greeting_body=raw[:3500])
    await state.set_state(AdminFSM.greeting_button)
    await message.answer(
        "Кнопка под приветкой?\n<code>Текст | https://ссылка</code>\nили нажмите «Без кнопки».",
        reply_markup=markup(
            [button("Без кнопки", "admin:greet:nobtn", icon="off")],
            [button("Отмена", "admin:greet", icon="cross")],
        ),
    )


@router.callback_query(F.data == "admin:greet:nobtn", StateFilter(AdminFSM.greeting_button))
async def greet_no_button(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    try:
        await greet_service.create_greeting(session, body=str(data.get("greeting_body") or ""))
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    rows = await greet_service.list_greetings(session)
    await safe_answer(call, "Сохранено")
    await safe_edit(call.message, _greet_text(rows), _greet_list_kb(rows))


@router.message(StateFilter(AdminFSM.greeting_button), F.text)
async def greet_button(message: Message, session: AsyncSession, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if "|" not in raw:
        await message.answer("Формат: <code>Текст | https://ссылка</code>")
        return
    label, url = (part.strip() for part in raw.split("|", 1))
    data = await state.get_data()
    await state.clear()
    try:
        await greet_service.create_greeting(
            session,
            body=str(data.get("greeting_body") or ""),
            button_text=label,
            button_url=url,
        )
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc.message}")
        return
    await message.answer("Приветка сохранена.", reply_markup=_back_catalog())


@router.callback_query(F.data.startswith("admin:greet:tg:"))
async def greet_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    row = await greet_service.toggle_greeting(session, parse_id(call.data))
    if row is None:
        await safe_answer(call, "Не найдена", alert=True)
        return
    rows = await greet_service.list_greetings(session)
    await safe_answer(call, "Вкл" if row.is_active else "Выкл")
    await safe_edit(call.message, _greet_text(rows), _greet_list_kb(rows))


@router.callback_query(F.data.startswith("admin:greet:del:"))
async def greet_delete(call: CallbackQuery, session: AsyncSession) -> None:
    await greet_service.delete_greeting(session, parse_id(call.data))
    rows = await greet_service.list_greetings(session)
    await safe_answer(call, "Удалено")
    await safe_edit(call.message, _greet_text(rows), _greet_list_kb(rows))


def _fmt_stats(stats: CampaignStats) -> str:
    return (
        f"клики {stats.clicks_day}/{stats.clicks_week}/{stats.clicks_all} · "
        f"люди {stats.users_day}/{stats.users_week}/{stats.users_all}"
    )


async def _camp_text(session: AsyncSession, bot_username: str) -> str:
    rows = await camp_service.list_campaigns(session)
    lines = [
        "📊 <b>Кампании</b>",
        "",
        "Ссылка <code>?start=c_КОД</code>. Клик — каждый заход, люди — уникальные.",
        "Цифры: день / неделя / всё время.",
        "",
    ]
    if not rows:
        lines.append("Пока нет. Создайте код и отдайте ссылку в закуп.")
    for row in rows:
        stats = await camp_service.campaign_stats(session, row.id)
        link = camp_service.campaign_link(bot_username, row.code)
        lines.append(f"<b>{h(row.code)}</b> · {_fmt_stats(stats)}\n<code>{h(link)}</code>")
    return "\n".join(lines)


def _camp_kb() -> InlineKeyboardMarkup:
    return markup(
        [button("Новая кампания", "admin:camp:new", icon="plus")],
        [button("Обновить", "admin:camp", icon="refresh")],
        [button("В каталог", "admin:catalog", icon="back")],
    )


@router.callback_query(F.data == "admin:camp")
async def camp_home(call: CallbackQuery, session: AsyncSession, state: FSMContext, bot_username: str) -> None:
    await state.clear()
    await safe_answer(call)
    await safe_edit(call.message, await _camp_text(session, bot_username), _camp_kb())


@router.callback_query(F.data == "admin:camp:new")
async def camp_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.campaign_code)
    await safe_answer(call)
    await safe_edit(
        call.message,
        "Код кампании латиницей, например <code>TGJUNE</code>.\nСсылка будет <code>?start=c_TGJUNE</code>.",
        markup([button("Отмена", "admin:camp", icon="cross")]),
    )


@router.message(StateFilter(AdminFSM.campaign_code), F.text)
async def camp_code(message: Message, session: AsyncSession, state: FSMContext, bot_username: str) -> None:
    raw = (message.text or "").strip()
    if not raw or raw.startswith("/"):
        await state.clear()
        return
    await state.clear()
    try:
        row = await camp_service.create_campaign(session, raw)
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc.message}")
        return
    link = camp_service.campaign_link(bot_username, row.code)
    await message.answer(
        f"Кампания <b>{h(row.code)}</b>\n<code>{h(link)}</code>",
        reply_markup=_camp_kb(),
    )
