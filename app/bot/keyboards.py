"""User keyboards."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.bot.utils import PAGE_SIZE, button, markup, pager, url_button
from app.db.models import BoostProduct, Task, TaskKind, Withdrawal, WithdrawalStatus
from app.op.base import Sponsor
from app.op.manual import parse_channel_entry
from app.services.gifts import GiftOffer
from app.services.tasks import task_target


def device_button(url: str) -> InlineKeyboardButton:
    """Opens the device-verification Mini App (private chats only)."""
    return InlineKeyboardButton(text="🛡 Подтвердить устройство", web_app=WebAppInfo(url=url))


def main_menu(is_admin: bool = False, device_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if device_url:
        rows.append([device_button(device_url)])
    rows += [
        [button("👤 Профиль", "menu:profile"), button("👥 Рефералы", "menu:refs")],
        [button("🎁 Ежедневка", "menu:daily"), button("📋 Задания", "menu:tasks")],
        [button("🚀 Бусты", "menu:boosts"), button("🏆 Топ", "menu:top:refs")],
        [button("💸 Вывод", "menu:withdraw"), button("🎟 Промокод", "menu:promo")],
        [button("❓ Помощь", "menu:help")],
    ]
    if is_admin:
        rows.append([button("🛠 Админка", "admin:home")])
    return markup(*rows)


def back_home(*extra_rows: list) -> InlineKeyboardMarkup:
    return markup(*extra_rows, [button("🏠 В меню", "menu:home")])


def profile_menu() -> InlineKeyboardMarkup:
    return markup(
        [button("📜 История", "menu:history:0"), button("📄 Мои заявки", "wd:list")],
        [button("🏠 В меню", "menu:home")],
    )


def history_menu(page: int, total: int) -> InlineKeyboardMarkup:
    return markup(pager("menu:history", page, total, PAGE_SIZE), [button("👤 Профиль", "menu:profile")])


def referrals_menu(link: str, share_text: str) -> InlineKeyboardMarkup:
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(share_text, safe='')}"
    return markup(
        [url_button("📤 Поделиться ссылкой", share_url)],
        [button("🏆 Топ рефереров", "menu:top:refs"), button("🏠 В меню", "menu:home")],
    )


def daily_menu(claimed: bool) -> InlineKeyboardMarkup:
    rows = []
    if not claimed:
        rows.append([button("🎁 Забрать награду", "daily:claim")])
    rows.append([button("📋 Задания", "menu:tasks"), button("🏠 В меню", "menu:home")])
    return markup(*rows)


def op_keyboard(sponsors: Sequence[Sponsor]) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for sponsor in sponsors:
        title = (sponsor.title or "Спонсор")[:32]
        row.append(url_button(f"➕ {title}", sponsor.url))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([button("✅ Я подписался", "op:verify")])
    return markup(*rows)


def tasks_keyboard(tasks: Sequence[Task], done: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for task in tasks:
        mark = "✅ " if task.id in done else ""
        rows.append([button(f"{mark}{task.title} · +{task.reward}⭐", f"task:view:{task.id}")])
    rows.append([button("🏠 В меню", "menu:home")])
    return markup(*rows)


def task_card(task: Task, done: bool) -> InlineKeyboardMarkup:
    rows = []
    target = task_target(task)
    if task.kind == TaskKind.SUBSCRIBE.value and target:
        entry = parse_channel_entry(target)
        if entry.has_join_link:
            rows.append([url_button(f"📢 {entry.title}"[:60], entry.url)])
        if not done:
            rows.append([button("🔄 Проверить подписку", f"task:do:{task.id}")])
    elif task.kind == TaskKind.CUSTOM.value and target:
        rows.append([url_button("🔗 Перейти", target)])
        if not done:
            rows.append([button("✅ Получить награду", f"task:do:{task.id}")])
    elif not done:
        label = {
            TaskKind.INVITE.value: "🔄 Проверить рефералов",
            TaskKind.STREAK.value: "🔄 Проверить серию",
        }.get(task.kind, "✅ Выполнить")
        rows.append([button(label, f"task:do:{task.id}")])
    rows.append([button("‹ К заданиям", "menu:tasks"), button("🏠 В меню", "menu:home")])
    return markup(*rows)


def boosts_keyboard(products: Sequence[BoostProduct]) -> InlineKeyboardMarkup:
    rows = [[button(f"{p.title} · {p.xtr_price} XTR", f"boost:view:{p.id}")] for p in products]
    rows.append([button("🏠 В меню", "menu:home")])
    return markup(*rows)


def boost_card(product: BoostProduct) -> InlineKeyboardMarkup:
    return markup(
        [button(f"💳 Купить за {product.xtr_price} XTR", f"boost:buy:{product.id}")],
        [button("‹ К бустам", "menu:boosts"), button("🏠 В меню", "menu:home")],
    )


def top_menu(mode: str) -> InlineKeyboardMarkup:
    refs = "• Рефералы" if mode == "refs" else "Рефералы"
    earn = "• Заработок 7д" if mode == "earn" else "Заработок 7д"
    return markup(
        [button(refs, "menu:top:refs"), button(earn, "menu:top:earn")],
        [button("👥 Моя ссылка", "menu:refs"), button("🏠 В меню", "menu:home")],
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
            chunk.append(button(f"{offer.emoji} {offer.star_count} ⭐", f"wd:g:{offer.id}"))
            if len(chunk) == 2:
                rows.append(chunk)
                chunk = []
        if chunk:
            rows.append(chunk)
        if total > per_page:
            nav: list[InlineKeyboardButton] = []
            if page > 0:
                nav.append(button("◀️", f"wd:page:{page - 1}"))
            nav.append(button(f"{page + 1}/{(total + per_page - 1) // per_page}", "noop"))
            if start + per_page < total:
                nav.append(button("▶️", f"wd:page:{page + 1}"))
            rows.append(nav)
    if catalog_error:
        rows.append([button("🔄 Обновить каталог", "menu:withdraw")])
    rows.append([button("📄 Мои заявки", "wd:list"), button("🏠 В меню", "menu:home")])
    return markup(*rows)


def withdraw_list_menu(items: Sequence[Withdrawal]) -> InlineKeyboardMarkup:
    rows = []
    for wd in items:
        if wd.status == WithdrawalStatus.PENDING.value:
            rows.append([button(f"✖ Отменить заявку #{wd.id}", f"wd:cancel:{wd.id}")])
    rows.append([button("💸 К выводу", "menu:withdraw"), button("🏠 В меню", "menu:home")])
    return markup(*rows)


def cancel_only(target: str = "menu:home") -> InlineKeyboardMarkup:
    return markup([button("Отмена", target)])


def help_menu(support: str) -> InlineKeyboardMarkup:
    rows = []
    if support:
        handle = support.lstrip("@")
        if handle and " " not in handle:
            rows.append([url_button("📨 Написать в поддержку", f"https://t.me/{handle}")])
    rows.append([button("📄 Условия", "menu:terms"), button("🏠 В меню", "menu:home")])
    return markup(*rows)
