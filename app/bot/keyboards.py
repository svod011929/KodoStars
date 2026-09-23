"""User keyboards — plain button text + premium ``icon_custom_emoji_id``."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.bot import emoji as pe
from app.bot.utils import PAGE_SIZE, button, markup, pager, url_button
from app.db.models import (
    AMBASSADOR_KIND_LABELS,
    AMBASSADOR_STATUS_LABELS,
    AmbassadorKind,
    AmbassadorStatus,
    BoostProduct,
    Task,
    TaskKind,
    Withdrawal,
    WithdrawalStatus,
)
from app.op.base import Sponsor
from app.services.channels import parse_channel_entry
from app.services.gifts import GiftOffer
from app.services.tasks import task_target


def device_button(url: str) -> InlineKeyboardButton:
    """Opens the device-verification Mini App (private chats only)."""
    return InlineKeyboardButton(
        text="Подтвердить устройство",
        web_app=WebAppInfo(url=url),
        icon_custom_emoji_id=pe.id_of("device"),
    )


def device_gate_keyboard(url: str) -> InlineKeyboardMarkup:
    return markup([device_button(url)])


def main_menu(
    is_admin: bool = False,
    device_url: str | None = None,
    l1_bonus: int = 0,
) -> InlineKeyboardMarkup:
    """Compact user menu: earn · social · money · help."""
    rows = []
    if device_url:
        rows.append([device_button(device_url)])
    ref_label = f"{l1_bonus} за друга" if l1_bonus > 0 else "Рефералы"
    rows += [
        [button(ref_label, "menu:refs", icon="people"), button("Ежедневка", "menu:daily", icon="gift")],
        [button("Задания", "menu:tasks", icon="tasks"), button("Профиль", "menu:profile", icon="profile")],
        [button("Вывод", "menu:withdraw", icon="withdraw"), button("Бусты", "menu:boosts", icon="boost")],
        [button("Топ", "menu:top:refs", icon="top"), button("Промокод", "menu:promo", icon="promo")],
        [button("Амбассадор", "menu:amb", icon="handshake"), button("Помощь", "menu:help", icon="help")],
    ]
    if is_admin:
        rows.append([button("Админка", "admin:home", icon="admin")])
    return markup(*rows)


def back_home(*extra_rows: list) -> InlineKeyboardMarkup:
    return markup(*extra_rows, [button("В меню", "menu:home", icon="home")])


def profile_menu() -> InlineKeyboardMarkup:
    return markup(
        [button("История", "menu:history:0", icon="scroll"), button("Мои заявки", "wd:list", icon="doc")],
        [button("В меню", "menu:home", icon="home")],
    )


def history_menu(page: int, total: int) -> InlineKeyboardMarkup:
    return markup(
        pager("menu:history", page, total, PAGE_SIZE),
        [button("Профиль", "menu:profile", icon="profile")],
    )


def greeting_keyboard(text: str | None, url: str | None) -> InlineKeyboardMarkup | None:
    if not text or not url:
        return None
    return markup([url_button(text, url)])


def referrals_menu(link: str, share_text: str) -> InlineKeyboardMarkup:
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(share_text, safe='')}"
    return markup(
        [url_button("Поделиться ссылкой", share_url, icon="share")],
        [button("Топ рефереров", "menu:top:refs", icon="top"), button("В меню", "menu:home", icon="home")],
    )


def daily_menu(claimed: bool) -> InlineKeyboardMarkup:
    rows = []
    if not claimed:
        rows.append([button("Забрать награду", "daily:claim", icon="gift")])
    rows.append(
        [button("Задания", "menu:tasks", icon="tasks"), button("В меню", "menu:home", icon="home")]
    )
    return markup(*rows)


def op_keyboard(sponsors: Sequence[Sponsor]) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for sponsor in sponsors:
        title = (sponsor.title or "Спонсор")[:32]
        row.append(url_button(title, sponsor.url, icon="subscribe"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([button("Я подписался", "op:verify", icon="check")])
    return markup(*rows)


def tasks_keyboard(tasks: Sequence[Task], done: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for task in tasks:
        icon = "check" if task.id in done else "tasks"
        rows.append([button(f"{task.title} · +{task.reward}", f"task:view:{task.id}", icon=icon)])
    rows.append([button("В меню", "menu:home", icon="home")])
    return markup(*rows)


def task_card(task: Task, done: bool) -> InlineKeyboardMarkup:
    rows = []
    target = task_target(task)
    if task.kind == TaskKind.SUBSCRIBE.value and target:
        entry = parse_channel_entry(target)
        if entry.has_join_link:
            rows.append([url_button(entry.title[:60], entry.url, icon="megaphone")])
        if not done:
            rows.append([button("Проверить подписку", f"task:do:{task.id}", icon="refresh")])
    elif task.kind == TaskKind.CUSTOM.value and target:
        rows.append([url_button("Перейти", target, icon="link")])
        if not done:
            rows.append([button("Получить награду", f"task:do:{task.id}", icon="check")])
    elif not done:
        label = {
            TaskKind.INVITE.value: "Проверить рефералов",
            TaskKind.STREAK.value: "Проверить серию",
        }.get(task.kind, "Выполнить")
        icon = "refresh" if task.kind in (TaskKind.INVITE.value, TaskKind.STREAK.value) else "check"
        rows.append([button(label, f"task:do:{task.id}", icon=icon)])
    rows.append(
        [button("К заданиям", "menu:tasks", icon="back"), button("В меню", "menu:home", icon="home")]
    )
    return markup(*rows)


def boosts_keyboard(products: Sequence[BoostProduct]) -> InlineKeyboardMarkup:
    rows = [[button(f"{p.title} · {p.xtr_price} XTR", f"boost:view:{p.id}", icon="boost")] for p in products]
    rows.append([button("В меню", "menu:home", icon="home")])
    return markup(*rows)


def boost_card(product: BoostProduct) -> InlineKeyboardMarkup:
    return markup(
        [button(f"Купить за {product.xtr_price} XTR", f"boost:buy:{product.id}", icon="payments")],
        [button("К бустам", "menu:boosts", icon="back"), button("В меню", "menu:home", icon="home")],
    )


def top_menu(mode: str) -> InlineKeyboardMarkup:
    refs = "• Рефералы" if mode == "refs" else "Рефералы"
    earn = "• Заработок 7д" if mode == "earn" else "Заработок 7д"
    return markup(
        [button(refs, "menu:top:refs", icon="people"), button(earn, "menu:top:earn", icon="growth")],
        [button("Моя ссылка", "menu:refs", icon="people"), button("В меню", "menu:home", icon="home")],
    )


def withdraw_keyboard(
    offers: Sequence[GiftOffer],
    *,
    enabled: bool,
    has_open: bool,
    page: int = 0,
    per_page: int = 8,
    device_url: str | None = None,
    catalog_error: bool = False,
) -> InlineKeyboardMarkup:
    rows = []
    if device_url:
        rows.append([device_button(device_url)])
        enabled = False  # verification comes first
    if enabled and not has_open and not catalog_error and offers:
        total = len(offers)
        start = page * per_page
        page_items = offers[start : start + per_page]
        chunk: list[InlineKeyboardButton] = []
        for offer in page_items:
            chunk.append(button(f"{offer.star_count} Stars", f"wd:g:{offer.id}", icon="gift"))
            if len(chunk) == 2:
                rows.append(chunk)
                chunk = []
        if chunk:
            rows.append(chunk)
        if total > per_page:
            nav: list[InlineKeyboardButton] = []
            if page > 0:
                nav.append(button("Назад", f"wd:page:{page - 1}", icon="left"))
            nav.append(button(f"{page + 1}/{(total + per_page - 1) // per_page}", "noop"))
            if start + per_page < total:
                nav.append(button("Далее", f"wd:page:{page + 1}", icon="right"))
            rows.append(nav)
    if catalog_error:
        rows.append([button("Обновить каталог", "menu:withdraw", icon="refresh")])
    rows.append(
        [button("Мои заявки", "wd:list", icon="doc"), button("В меню", "menu:home", icon="home")]
    )
    return markup(*rows)


def withdraw_list_menu(items: Sequence[Withdrawal]) -> InlineKeyboardMarkup:
    rows = []
    for wd in items:
        if wd.status == WithdrawalStatus.PENDING.value:
            rows.append([button(f"Отменить заявку #{wd.id}", f"wd:cancel:{wd.id}", icon="cross")])
    rows.append(
        [button("К выводу", "menu:withdraw", icon="withdraw"), button("В меню", "menu:home", icon="home")]
    )
    return markup(*rows)


def cancel_only(target: str = "menu:home") -> InlineKeyboardMarkup:
    return markup([button("Отмена", target, icon="cross")])


def help_menu(support: str) -> InlineKeyboardMarkup:
    rows = []
    if support:
        handle = support.lstrip("@")
        if handle and " " not in handle:
            rows.append([url_button("Написать в поддержку", f"https://t.me/{handle}", icon="mail")])
    rows.append(
        [button("Условия", "menu:terms", icon="doc"), button("В меню", "menu:home", icon="home")]
    )
    return markup(*rows)


def ambassador_home(slots: Sequence) -> InlineKeyboardMarkup:
    rows = []
    for slot in slots[:12]:
        kind = AMBASSADOR_KIND_LABELS.get(slot.kind, slot.kind)
        status = AMBASSADOR_STATUS_LABELS.get(slot.status, slot.status)
        rows.append(
            [button(f"{kind}: {slot.title[:18]} · {status}", f"amb:slot:{slot.id}", icon="handshake")]
        )
    rows.append([button("Подать заявку", "amb:new", icon="plus")])
    rows.append([button("В меню", "menu:home", icon="home")])
    return markup(*rows)


def ambassador_kind_pick() -> InlineKeyboardMarkup:
    return markup(
        [
            button("Канал", "amb:kind:channel", icon="megaphone"),
            button("Чат", "amb:kind:chat", icon="people"),
        ],
        [button("Бот", "amb:kind:bot", icon="bot")],
        [button("Отмена", "menu:amb", icon="cross")],
    )


def ambassador_slot_card(slot, *, today_code: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if slot.status == AmbassadorStatus.APPROVED.value:
        rows.append([button("Получить промокод", f"amb:claim:{slot.id}", icon="promo")])
        if today_code and slot.kind != AmbassadorKind.BOT.value and slot.chat_id:
            rows.append([button("Опубликовать сегодня", f"amb:post:{slot.id}", icon="megaphone")])
    rows.append([button("К списку", "menu:amb", icon="back"), button("В меню", "menu:home", icon="home")])
    return markup(*rows)
