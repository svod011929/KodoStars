"""Admin keyboards."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup

from app.bot.utils import PAGE_SIZE, button, markup, pager
from app.config import RUNTIME_OVERRIDABLE, RUNTIME_SETTING_LABELS
from app.db.models import (
    BROADCAST_AUDIENCE_LABELS,
    TASK_KIND_LABELS,
    Admin,
    BoostKind,
    BoostProduct,
    Broadcast,
    Payment,
    PromoCode,
    Task,
    User,
    Withdrawal,
    WithdrawalStatus,
)
from app.op.gate import CASCADE, PROVIDER_TITLES

BACK = "‹ Назад"


def home() -> InlineKeyboardMarkup:
    return markup(
        [button("📊 Статистика", "admin:stats"), button("👥 Пользователи", "admin:users")],
        [button("💸 Выводы", "admin:wd"), button("📣 Рассылка", "admin:bc")],
        [button("📋 Задания", "admin:tasks"), button("🚀 Бусты", "admin:boosts")],
        [button("🎟 Промокоды", "admin:promo:list:0"), button("💳 Платежи", "admin:pay:0")],
        [button("⚙️ Настройки", "admin:set"), button("🔒 PiarFlow", "admin:prov")],
        [button("🛡 Админы", "admin:adm"), button("🧾 Журнал", "admin:audit:0")],
        [button("🕵️ Антифрод", "admin:fraud:0"), button("🗂 Данные", "admin:data")],
        [button("🏠 В меню", "menu:home")],
    )


def back_home(*rows: list) -> InlineKeyboardMarkup:
    return markup(*rows, [button(BACK, "admin:home")])


def stats() -> InlineKeyboardMarkup:
    return markup(
        [button("🔄 Обновить", "admin:stats"), button("🧮 Сверка балансов", "admin:reconcile")],
        [button(BACK, "admin:home")],
    )


def reconcile(has_drift: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_drift:
        rows.append([button("🛠 Исправить по леджеру", "admin:reconcile:fix")])
    rows.append([button("📊 Статистика", "admin:stats"), button(BACK, "admin:home")])
    return markup(*rows)


# --- users --------------------------------------------------------------------------


def users_home(recent: Sequence[User]) -> InlineKeyboardMarkup:
    rows = [[button(f"{u.display_name[:24]} · {u.id}", f"admin:u:{u.id}")] for u in recent[:5]]
    rows.append([button("🕵️ Подозрительные", "admin:suspicious"), button(BACK, "admin:home")])
    return markup(*rows)


def user_card(user: User, *, is_owner_viewer: bool, open_wd: Withdrawal | None) -> InlineKeyboardMarkup:
    ban = (
        button("♻️ Разбанить", f"admin:u:{user.id}:unban")
        if user.is_banned
        else button("🚫 Бан", f"admin:u:{user.id}:ban")
    )
    rows = [
        [button("➕/➖ Баланс", f"admin:u:{user.id}:adj"), ban],
        [
            button("📜 Леджер", f"admin:u:{user.id}:ledger:0"),
            button("👥 Рефералы", f"admin:u:{user.id}:refs"),
        ],
        [button("💬 Написать", f"admin:u:{user.id}:msg"), button("📝 Заметка", f"admin:u:{user.id}:note")],
        [button("💳 Платежи", f"admin:u:{user.id}:pays"), button("🕵️ Фрод", f"admin:u:{user.id}:fraud")],
    ]
    trust = (
        button("🤝 Снять доверие", f"admin:u:{user.id}:trust:0")
        if user.is_trusted
        else button("🤝 Доверенный (не твинк)", f"admin:u:{user.id}:trust:1")
    )
    rows.append([trust])
    if open_wd is not None:
        rows.append([button(f"💸 Заявка #{open_wd.id}", f"admin:wd:view:{open_wd.id}")])
    rows.append([button("🔄 Обновить", f"admin:u:{user.id}"), button("👥 Пользователи", "admin:users")])
    return markup(*rows)


def user_sub(user_id: int, *extra: list) -> InlineKeyboardMarkup:
    return markup(*extra, [button("👤 Карточка", f"admin:u:{user_id}"), button(BACK, "admin:users")])


def user_ledger(user_id: int, page: int, total: int) -> InlineKeyboardMarkup:
    return markup(
        pager(f"admin:u:{user_id}:ledger", page, total, PAGE_SIZE),
        [button("👤 Карточка", f"admin:u:{user_id}")],
    )


def cancel_to(target: str) -> InlineKeyboardMarkup:
    return markup([button("Отмена", target)])


def fraud(page: int, total: int, user_id: int | None) -> InlineKeyboardMarkup:
    prefix = f"admin:u:{user_id}:fraud" if user_id else "admin:fraud"
    back = button("👤 Карточка", f"admin:u:{user_id}") if user_id else button(BACK, "admin:home")
    return markup(
        pager(prefix, page, total, PAGE_SIZE),
        [button("🕵️ Подозрительные", "admin:suspicious"), button("👯 Твинки", "admin:twinks")],
        [back],
    )


def suspicious(rows: Sequence[tuple[User, int, int]]) -> InlineKeyboardMarkup:
    buttons = [
        [button(f"{u.display_name[:20]} · {act}/{total}", f"admin:u:{u.id}")] for u, total, act in rows[:8]
    ]
    buttons.append([button("🕵️ События", "admin:fraud:0"), button("👯 Твинки", "admin:twinks")])
    buttons.append([button(BACK, "admin:home")])
    return markup(*buttons)


def twinks(clusters: Sequence[tuple[str, int, Sequence[User]]]) -> InlineKeyboardMarkup:
    rows = []
    for _fp, count, members in clusters[:8]:
        first = members[0] if members else None
        if first is not None:
            rows.append([button(f"{first.display_name[:18]} +{count - 1}", f"admin:u:{first.id}")])
    rows.append([button("🕵️ События", "admin:fraud:0"), button(BACK, "admin:home")])
    return markup(*rows)


# --- withdrawals --------------------------------------------------------------------


def withdrawals_home(pending: int, approved: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(f"⏳ Ожидают ({pending})", "admin:wd:list:pending:0"),
            button(f"🟢 Согласованы ({approved})", "admin:wd:list:approved:0"),
        ],
        [button("📚 История", "admin:wd:list:history:0"), button("🔄 Обновить", "admin:wd")],
        [button(BACK, "admin:home")],
    )


def withdrawals_list(
    items: Sequence[Withdrawal], names: dict[int, str], filter_name: str, page: int, total: int
) -> InlineKeyboardMarkup:
    icons = {
        WithdrawalStatus.PENDING.value: "⏳",
        WithdrawalStatus.APPROVED_MANUAL.value: "🟢",
        WithdrawalStatus.SENT.value: "✅",
        WithdrawalStatus.REJECTED.value: "🔴",
        WithdrawalStatus.CANCELLED.value: "↩️",
    }
    rows = [
        [
            button(
                f"{icons.get(w.status, '')} #{w.id} · {w.gift_label} · {names.get(w.user_id, w.user_id)}"[
                    :60
                ],
                f"admin:wd:view:{w.id}",
            )
        ]
        for w in items
    ]
    rows.append(pager(f"admin:wd:list:{filter_name}", page, total, PAGE_SIZE))
    rows.append([button("💸 Выводы", "admin:wd"), button(BACK, "admin:home")])
    return markup(*rows)


def withdrawal_actions(wd_id: int, status: str, *, has_gift: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if status == WithdrawalStatus.PENDING.value:
        rows.append(
            [button("✅ Согласовать", f"admin:wd:ok:{wd_id}"), button("🔴 Отклонить", f"admin:wd:no:{wd_id}")]
        )
    elif status == WithdrawalStatus.APPROVED_MANUAL.value:
        rows.append([button("⭐ Отправить через Fragment", f"admin:wd:fragment:{wd_id}")])
        rows.append([button("✅ Уже отправил вручную", f"admin:wd:sent:{wd_id}")])
        rows.append([button("🔴 Отклонить", f"admin:wd:no:{wd_id}")])
    rows.append([button("🔎 Открыть заявку", f"admin:wd:view:{wd_id}")])
    return markup(*rows)


def withdrawal_card(wd: Withdrawal) -> InlineKeyboardMarkup:
    rows = []
    if wd.status == WithdrawalStatus.PENDING.value:
        rows.append(
            [button("✅ Согласовать", f"admin:wd:ok:{wd.id}"), button("🔴 Отклонить", f"admin:wd:no:{wd.id}")]
        )
    elif wd.status == WithdrawalStatus.APPROVED_MANUAL.value:
        rows.append([button("⭐ Отправить через Fragment", f"admin:wd:fragment:{wd.id}")])
        rows.append([button("✅ Уже отправил вручную", f"admin:wd:sent:{wd.id}")])
        rows.append([button("🔴 Отклонить (вернуть Stars)", f"admin:wd:no:{wd.id}")])
    rows.append(
        [button("👤 Пользователь", f"admin:u:{wd.user_id}"), button("🔄 Обновить", f"admin:wd:view:{wd.id}")]
    )
    rows.append([button("⏳ Очередь", "admin:wd:list:pending:0"), button("💸 Выводы", "admin:wd")])
    return markup(*rows)


# --- broadcast ----------------------------------------------------------------------


def broadcast_home(running: Broadcast | None, history: Sequence[Broadcast]) -> InlineKeyboardMarkup:
    rows = [[button("✉️ Новая рассылка", "admin:bc:new")]]
    if running is not None:
        rows.append([button(f"▶️ Рассылка #{running.id}", f"admin:bc:view:{running.id}")])
    for item in history[:3]:
        if running is not None and item.id == running.id:
            continue
        rows.append(
            [button(f"#{item.id} · {item.status} · {item.sent}/{item.total}", f"admin:bc:view:{item.id}")]
        )
    rows.append([button(BACK, "admin:home")])
    return markup(*rows)


def broadcast_button_step() -> InlineKeyboardMarkup:
    return markup([button("Без кнопки", "admin:bc:btn:no")], [button("Отмена", "admin:bc")])


def broadcast_audience() -> InlineKeyboardMarkup:
    rows = [[button(label, f"admin:bc:aud:{key}")] for key, label in BROADCAST_AUDIENCE_LABELS.items()]
    rows.append([button("Отмена", "admin:bc")])
    return markup(*rows)


def broadcast_confirm() -> InlineKeyboardMarkup:
    return markup(
        [button("🚀 Запустить", "admin:bc:go"), button("👁 Тест себе", "admin:bc:test")],
        [button("Отмена", "admin:bc")],
    )


def broadcast_progress(b: Broadcast, running: bool) -> InlineKeyboardMarkup:
    rows = []
    if running:
        rows.append([button("⏹ Остановить", f"admin:bc:stop:{b.id}")])
    rows.append([button("🔄 Обновить", f"admin:bc:view:{b.id}"), button("📣 Рассылки", "admin:bc")])
    return markup(*rows)


# --- catalog ------------------------------------------------------------------------


def tasks_home(tasks: Sequence[Task]) -> InlineKeyboardMarkup:
    rows = [
        [button(f"{'🟢' if t.is_active else '⚪'} {t.title[:28]} · {t.reward}⭐", f"admin:task:{t.id}")]
        for t in tasks[:12]
    ]
    rows.append([button("➕ Новое задание", "admin:task:new"), button(BACK, "admin:home")])
    return markup(*rows)


def task_card(task: Task) -> InlineKeyboardMarkup:
    toggle = "⚪ Выключить" if task.is_active else "🟢 Включить"
    return markup(
        [button(toggle, f"admin:task:{task.id}:tg"), button("🗑 Удалить", f"admin:task:{task.id}:del")],
        [
            button("✏️ Название", f"admin:task:{task.id}:e:title"),
            button("✏️ Описание", f"admin:task:{task.id}:e:desc"),
        ],
        [
            button("✏️ Награда", f"admin:task:{task.id}:e:reward"),
            button("✏️ Условие", f"admin:task:{task.id}:e:target"),
        ],
        [button("✏️ Порядок", f"admin:task:{task.id}:e:order"), button("📋 Задания", "admin:tasks")],
    )


def task_kinds() -> InlineKeyboardMarkup:
    rows = [[button(label, f"admin:task:new:{kind}")] for kind, label in TASK_KIND_LABELS.items()]
    rows.append([button("Отмена", "admin:tasks")])
    return markup(*rows)


def boosts_home(products: Sequence[BoostProduct]) -> InlineKeyboardMarkup:
    rows = [
        [button(f"{'🟢' if p.is_active else '⚪'} {p.title[:26]} · {p.xtr_price} XTR", f"admin:boost:{p.id}")]
        for p in products[:12]
    ]
    rows.append([button("➕ Новый буст", "admin:boost:new"), button(BACK, "admin:home")])
    return markup(*rows)


def boost_card(product: BoostProduct) -> InlineKeyboardMarkup:
    toggle = "⚪ Выключить" if product.is_active else "🟢 Включить"
    param = (
        button("✏️ Кол-во Stars", f"admin:boost:{product.id}:e:amount")
        if product.kind == BoostKind.STARS_PACK.value
        else button("✏️ Множитель/часы", f"admin:boost:{product.id}:e:mult")
    )
    return markup(
        [
            button(toggle, f"admin:boost:{product.id}:tg"),
            button("🗑 Удалить", f"admin:boost:{product.id}:del"),
        ],
        [
            button("✏️ Название", f"admin:boost:{product.id}:e:title"),
            button("✏️ Описание", f"admin:boost:{product.id}:e:desc"),
        ],
        [button("✏️ Цена XTR", f"admin:boost:{product.id}:e:price"), param],
        [button("🚀 Бусты", "admin:boosts")],
    )


def boost_kinds() -> InlineKeyboardMarkup:
    return markup(
        [button("Пак внутренних Stars", f"admin:boost:new:{BoostKind.STARS_PACK.value}")],
        [button("Множитель на время", f"admin:boost:new:{BoostKind.MULTIPLIER.value}")],
        [button("Отмена", "admin:boosts")],
    )


# --- promo --------------------------------------------------------------------------


def promo_home(items: Sequence[PromoCode], page: int, total: int) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                f"{'🟢' if p.is_active else '⚪'} {p.code} · +{p.reward}⭐ · {p.uses}", f"admin:promo:{p.id}"
            )
        ]
        for p in items
    ]
    rows.append(pager("admin:promo:list", page, total, PAGE_SIZE))
    rows.append([button("➕ Новый промокод", "admin:promo:new"), button(BACK, "admin:home")])
    return markup(*rows)


def promo_card(promo: PromoCode) -> InlineKeyboardMarkup:
    toggle = "⚪ Выключить" if promo.is_active else "🟢 Включить"
    return markup(
        [button(toggle, f"admin:promo:{promo.id}:tg"), button("🗑 Удалить", f"admin:promo:{promo.id}:del")],
        [button("🎟 Промокоды", "admin:promo:list:0")],
    )


# --- payments -----------------------------------------------------------------------


def payments_home(items: Sequence[Payment], page: int, total: int) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                f"{'↩️' if p.status == 'refunded' else '✅'} #{p.id} · {p.xtr_amount} XTR · {p.user_id}",
                f"admin:pay:view:{p.id}",
            )
        ]
        for p in items
    ]
    rows.append(pager("admin:pay", page, total, PAGE_SIZE))
    rows.append([button(BACK, "admin:home")])
    return markup(*rows)


def payment_card(payment: Payment) -> InlineKeyboardMarkup:
    rows = []
    if payment.status != "refunded":
        rows.append([button("↩️ Вернуть платёж", f"admin:pay:refund:{payment.id}")])
    rows.append(
        [button("👤 Пользователь", f"admin:u:{payment.user_id}"), button("💳 Платежи", "admin:pay:0")]
    )
    return markup(*rows)


def refund_confirm(payment_id: int) -> InlineKeyboardMarkup:
    return markup(
        [button("✅ Да, вернуть", f"admin:pay:refund:{payment_id}:yes")],
        [button("Отмена", f"admin:pay:view:{payment_id}")],
    )


# --- settings / providers / channels / admins -----------------------------------------


def settings_home() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for key in RUNTIME_OVERRIDABLE:
        row.append(button(RUNTIME_SETTING_LABELS.get(key, key)[:30], f"admin:set:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([button(BACK, "admin:home")])
    return markup(*rows)


def setting_edit(key: str, overridden: bool, is_bool: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_bool:
        rows.append(
            [button("🟢 Включить", f"admin:set:{key}:on"), button("⚪ Выключить", f"admin:set:{key}:off")]
        )
    if overridden:
        rows.append([button("↩️ Сбросить к .env", f"admin:set:{key}:reset")])
    rows.append([button("⚙️ Настройки", "admin:set")])
    return markup(*rows)


def providers(states: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = [
        [button(f"{'🟢' if states.get(name) else '⚪'} {PROVIDER_TITLES[name]}", f"admin:prov:tg:{name}")]
        for name in CASCADE
    ]
    rows.append([button(BACK, "admin:home")])
    return markup(*rows)


def admins(rows_db: Sequence[Admin], can_manage: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_manage:
        rows.extend([[button(f"🗑 Удалить {row.user_id}", f"admin:adm:del:{row.user_id}")] for row in rows_db])
        rows.append([button("➕ Добавить админа", "admin:adm:add")])
    rows.append([button(BACK, "admin:home")])
    return markup(*rows)


# --- audit / data -------------------------------------------------------------------


def audit(page: int, total: int) -> InlineKeyboardMarkup:
    return markup(pager("admin:audit", page, total, PAGE_SIZE), [button(BACK, "admin:home")])


def data_home() -> InlineKeyboardMarkup:
    return markup(
        [button("⬇️ Пользователи CSV", "admin:exp:users"), button("⬇️ Выводы CSV", "admin:exp:wd")],
        [button("⬇️ Леджер CSV", "admin:exp:ledger"), button("⬇️ Платежи CSV", "admin:exp:pay")],
        [button("⬆️ Импорт пользователей", "admin:import")],
        [button(BACK, "admin:home")],
    )
