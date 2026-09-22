"""Admin keyboards."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup

from app.bot.utils import PAGE_SIZE, button, markup, pager
from app.config import (
    RUNTIME_OVERRIDABLE,
    RUNTIME_SETTING_LABELS,
    SETTINGS_GROUP_ICONS,
    SETTINGS_GROUP_LABELS,
    SETTINGS_GROUPS,
    setting_group,
)
from app.db.models import (
    AMBASSADOR_KIND_LABELS,
    AMBASSADOR_STATUS_LABELS,
    BROADCAST_AUDIENCE_LABELS,
    TASK_KIND_LABELS,
    Admin,
    AmbassadorKind,
    AmbassadorSlot,
    AmbassadorStatus,
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


def _back(target: str = "admin:home"):
    return button("Назад", target, icon="back")


def home(pending: int = 0, amb_pending: int = 0) -> InlineKeyboardMarkup:
    """Compact admin root: operations · products · traffic · system hubs."""
    wd_label = f"Выводы ({pending})" if pending else "Выводы"
    amb_label = f"Амбассадоры ({amb_pending})" if amb_pending else "Амбассадоры"
    return markup(
        [button("Статистика", "admin:stats", icon="stats"), button("Пользователи", "admin:users", icon="users")],
        [button(wd_label, "admin:wd", icon="withdraw"), button(amb_label, "admin:amb", icon="handshake")],
        [button("Рассылка", "admin:bc", icon="broadcast"), button("Каталог", "admin:catalog", icon="box")],
        [button("ОП", "admin:prov", icon="lock"), button("Система", "admin:system", icon="admin")],
        [button("Настройки", "admin:set", icon="settings"), button("В меню", "menu:home", icon="home")],
    )


def catalog_hub() -> InlineKeyboardMarkup:
    return markup(
        [button("Задания", "admin:tasks", icon="tasks"), button("Бусты", "admin:boosts", icon="boost")],
        [button("Промокоды", "admin:promo:list:0", icon="promo")],
        [_back()],
    )


def system_hub() -> InlineKeyboardMarkup:
    return markup(
        [button("Платежи", "admin:pay:0", icon="payments"), button("Админы", "admin:adm", icon="shield")],
        [button("Журнал", "admin:audit:0", icon="audit"), button("Антифрод", "admin:fraud:0", icon="fraud")],
        [button("Данные", "admin:data", icon="data")],
        [_back()],
    )


def back_home(*rows: list) -> InlineKeyboardMarkup:
    return markup(*rows, [_back()])


def stats() -> InlineKeyboardMarkup:
    return markup(
        [button("Обновить", "admin:stats", icon="refresh"), button("Сверка", "admin:reconcile", icon="code")],
        [button("PiarFlow трафик", "admin:pf:stats", icon="megaphone")],
        [_back()],
    )


def reconcile(has_drift: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_drift:
        rows.append([button("Исправить по леджеру", "admin:reconcile:fix", icon="admin")])
    rows.append([button("Статистика", "admin:stats", icon="stats"), _back()])
    return markup(*rows)


# --- users --------------------------------------------------------------------------


def users_home(recent: Sequence[User]) -> InlineKeyboardMarkup:
    rows = [[button(f"{u.display_name[:24]} · {u.id}", f"admin:u:{u.id}", icon="profile")] for u in recent[:5]]
    rows.append([button("Подозрительные", "admin:suspicious", icon="fraud"), _back()])
    return markup(*rows)


def user_card(user: User, *, is_owner_viewer: bool, open_wd: Withdrawal | None) -> InlineKeyboardMarkup:
    ban = (
        button("Разбанить", f"admin:u:{user.id}:unban", icon="unban")
        if user.is_banned
        else button("Бан", f"admin:u:{user.id}:ban", icon="ban")
    )
    rows = [
        [button("Баланс", f"admin:u:{user.id}:adj", icon="coin"), ban],
        [
            button("Леджер", f"admin:u:{user.id}:ledger:0", icon="scroll"),
            button("Рефералы", f"admin:u:{user.id}:refs", icon="people"),
        ],
        [
            button("Написать", f"admin:u:{user.id}:msg", icon="write"),
            button("Заметка", f"admin:u:{user.id}:note", icon="pencil"),
        ],
        [
            button("Платежи", f"admin:u:{user.id}:pays", icon="payments"),
            button("Фрод", f"admin:u:{user.id}:fraud", icon="fraud"),
        ],
    ]
    trust = (
        button("Снять доверие", f"admin:u:{user.id}:trust:0", icon="handshake")
        if user.is_trusted
        else button("Доверенный (не твинк)", f"admin:u:{user.id}:trust:1", icon="handshake")
    )
    rows.append([trust])
    if open_wd is not None:
        rows.append([button(f"Заявка #{open_wd.id}", f"admin:wd:view:{open_wd.id}", icon="withdraw")])
    rows.append(
        [
            button("Обновить", f"admin:u:{user.id}", icon="refresh"),
            button("Пользователи", "admin:users", icon="users"),
        ]
    )
    return markup(*rows)


def user_sub(user_id: int, *extra: list) -> InlineKeyboardMarkup:
    return markup(
        *extra,
        [button("Карточка", f"admin:u:{user_id}", icon="profile"), _back("admin:users")],
    )


def user_ledger(user_id: int, page: int, total: int) -> InlineKeyboardMarkup:
    return markup(
        pager(f"admin:u:{user_id}:ledger", page, total, PAGE_SIZE),
        [button("Карточка", f"admin:u:{user_id}", icon="profile")],
    )


def cancel_to(target: str) -> InlineKeyboardMarkup:
    return markup([button("Отмена", target, icon="cross")])


def fraud(page: int, total: int, user_id: int | None) -> InlineKeyboardMarkup:
    prefix = f"admin:u:{user_id}:fraud" if user_id else "admin:fraud"
    back = button("Карточка", f"admin:u:{user_id}", icon="profile") if user_id else _back("admin:system")
    return markup(
        pager(prefix, page, total, PAGE_SIZE),
        [
            button("Подозрительные", "admin:suspicious", icon="fraud"),
            button("Твинки", "admin:twinks", icon="twins"),
        ],
        [back],
    )


def suspicious(rows: Sequence[tuple[User, int, int]]) -> InlineKeyboardMarkup:
    buttons = [
        [button(f"{u.display_name[:20]} · {act}/{total}", f"admin:u:{u.id}", icon="profile")]
        for u, total, act in rows[:8]
    ]
    buttons.append(
        [
            button("События", "admin:fraud:0", icon="fraud"),
            button("Твинки", "admin:twinks", icon="twins"),
        ]
    )
    buttons.append([_back("admin:system")])
    return markup(*buttons)


def twinks(clusters: Sequence[tuple[str, int, Sequence[User]]]) -> InlineKeyboardMarkup:
    rows = []
    for _fp, count, members in clusters[:8]:
        first = members[0] if members else None
        if first is not None:
            rows.append(
                [button(f"{first.display_name[:18]} +{count - 1}", f"admin:u:{first.id}", icon="twins")]
            )
    rows.append([button("События", "admin:fraud:0", icon="fraud"), _back("admin:system")])
    return markup(*rows)


# --- withdrawals --------------------------------------------------------------------


def withdrawals_home(pending: int, approved: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(f"Ожидают ({pending})", "admin:wd:list:pending:0", icon="wait"),
            button(f"Согласованы ({approved})", "admin:wd:list:approved:0", icon="ok_green"),
        ],
        [
            button("История", "admin:wd:list:history:0", icon="scroll"),
            button("Обновить", "admin:wd", icon="refresh"),
        ],
        [_back()],
    )


def withdrawals_list(
    items: Sequence[Withdrawal], names: dict[int, str], filter_name: str, page: int, total: int
) -> InlineKeyboardMarkup:
    icons = {
        WithdrawalStatus.PENDING.value: "wait",
        WithdrawalStatus.APPROVED_MANUAL.value: "ok_green",
        WithdrawalStatus.SENT.value: "check",
        WithdrawalStatus.REJECTED.value: "no_entry",
        WithdrawalStatus.CANCELLED.value: "undo",
    }
    rows = [
        [
            button(
                f"#{w.id} · {w.gift_label} · {names.get(w.user_id, w.user_id)}"[:60],
                f"admin:wd:view:{w.id}",
                icon=icons.get(w.status),
            )
        ]
        for w in items
    ]
    rows.append(pager(f"admin:wd:list:{filter_name}", page, total, PAGE_SIZE))
    rows.append([button("Выводы", "admin:wd", icon="withdraw"), _back()])
    return markup(*rows)


def withdrawal_actions(wd_id: int, status: str, *, has_gift: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if status == WithdrawalStatus.PENDING.value:
        rows.append(
            [
                button("Согласовать", f"admin:wd:ok:{wd_id}", icon="check"),
                button("Отклонить", f"admin:wd:no:{wd_id}", icon="no_entry"),
            ]
        )
    elif status == WithdrawalStatus.APPROVED_MANUAL.value:
        rows.append([button("Отправить через Fragment", f"admin:wd:fragment:{wd_id}", icon="star")])
        rows.append([button("Уже отправил вручную", f"admin:wd:sent:{wd_id}", icon="check")])
        rows.append([button("Отклонить", f"admin:wd:no:{wd_id}", icon="no_entry")])
    rows.append([button("Открыть заявку", f"admin:wd:view:{wd_id}", icon="eye")])
    return markup(*rows)


def withdrawal_card(wd: Withdrawal) -> InlineKeyboardMarkup:
    rows = []
    if wd.status == WithdrawalStatus.PENDING.value:
        rows.append(
            [
                button("Согласовать", f"admin:wd:ok:{wd.id}", icon="check"),
                button("Отклонить", f"admin:wd:no:{wd.id}", icon="no_entry"),
            ]
        )
    elif wd.status == WithdrawalStatus.APPROVED_MANUAL.value:
        rows.append([button("Отправить через Fragment", f"admin:wd:fragment:{wd.id}", icon="star")])
        rows.append([button("Уже отправил вручную", f"admin:wd:sent:{wd.id}", icon="check")])
        rows.append([button("Отклонить (вернуть Stars)", f"admin:wd:no:{wd.id}", icon="no_entry")])
    rows.append(
        [
            button("Пользователь", f"admin:u:{wd.user_id}", icon="profile"),
            button("Обновить", f"admin:wd:view:{wd.id}", icon="refresh"),
        ]
    )
    rows.append(
        [
            button("Очередь", "admin:wd:list:pending:0", icon="wait"),
            button("Выводы", "admin:wd", icon="withdraw"),
        ]
    )
    return markup(*rows)


# --- broadcast ----------------------------------------------------------------------


def broadcast_home(running: Broadcast | None, history: Sequence[Broadcast]) -> InlineKeyboardMarkup:
    rows = [[button("Новая рассылка", "admin:bc:new", icon="letter")]]
    if running is not None:
        rows.append([button(f"Рассылка #{running.id}", f"admin:bc:view:{running.id}", icon="play")])
    for item in history[:3]:
        if running is not None and item.id == running.id:
            continue
        rows.append(
            [
                button(
                    f"#{item.id} · {item.status} · {item.sent}/{item.total}",
                    f"admin:bc:view:{item.id}",
                    icon="broadcast",
                )
            ]
        )
    rows.append([_back()])
    return markup(*rows)


def broadcast_button_step() -> InlineKeyboardMarkup:
    return markup(
        [button("Без кнопки", "admin:bc:btn:no", icon="cross")],
        [button("Отмена", "admin:bc", icon="cross")],
    )


def broadcast_audience() -> InlineKeyboardMarkup:
    rows = [[button(label, f"admin:bc:aud:{key}", icon="users")] for key, label in BROADCAST_AUDIENCE_LABELS.items()]
    rows.append([button("Отмена", "admin:bc", icon="cross")])
    return markup(*rows)


def broadcast_confirm() -> InlineKeyboardMarkup:
    return markup(
        [
            button("Запустить", "admin:bc:go", icon="boost"),
            button("Тест себе", "admin:bc:test", icon="eye"),
        ],
        [button("Отмена", "admin:bc", icon="cross")],
    )


def broadcast_progress(b: Broadcast, running: bool) -> InlineKeyboardMarkup:
    rows = []
    if running:
        rows.append([button("Остановить", f"admin:bc:stop:{b.id}", icon="stop_btn")])
    rows.append(
        [
            button("Обновить", f"admin:bc:view:{b.id}", icon="refresh"),
            button("Рассылки", "admin:bc", icon="broadcast"),
        ]
    )
    return markup(*rows)


# --- catalog ------------------------------------------------------------------------


def tasks_home(tasks: Sequence[Task]) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                f"{t.title[:28]} · {t.reward}",
                f"admin:task:{t.id}",
                icon="ok_green" if t.is_active else "off",
            )
        ]
        for t in tasks[:12]
    ]
    rows.append([button("Новое задание", "admin:task:new", icon="plus"), _back("admin:catalog")])
    return markup(*rows)


def task_card(task: Task) -> InlineKeyboardMarkup:
    toggle = "Выключить" if task.is_active else "Включить"
    toggle_icon = "off" if task.is_active else "ok_green"
    return markup(
        [
            button(toggle, f"admin:task:{task.id}:tg", icon=toggle_icon),
            button("Удалить", f"admin:task:{task.id}:del", icon="trash"),
        ],
        [
            button("Название", f"admin:task:{task.id}:e:title", icon="pencil"),
            button("Описание", f"admin:task:{task.id}:e:desc", icon="pencil"),
        ],
        [
            button("Награда", f"admin:task:{task.id}:e:reward", icon="pencil"),
            button("Условие", f"admin:task:{task.id}:e:target", icon="pencil"),
        ],
        [
            button("Порядок", f"admin:task:{task.id}:e:order", icon="pencil"),
            button("Задания", "admin:tasks", icon="tasks"),
        ],
    )


def task_kinds() -> InlineKeyboardMarkup:
    rows = [[button(label, f"admin:task:new:{kind}", icon="tasks")] for kind, label in TASK_KIND_LABELS.items()]
    rows.append([button("Отмена", "admin:tasks", icon="cross")])
    return markup(*rows)


def boosts_home(products: Sequence[BoostProduct]) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                f"{p.title[:26]} · {p.xtr_price} XTR",
                f"admin:boost:{p.id}",
                icon="ok_green" if p.is_active else "off",
            )
        ]
        for p in products[:12]
    ]
    rows.append([button("Новый буст", "admin:boost:new", icon="plus"), _back("admin:catalog")])
    return markup(*rows)


def boost_card(product: BoostProduct) -> InlineKeyboardMarkup:
    toggle = "Выключить" if product.is_active else "Включить"
    toggle_icon = "off" if product.is_active else "ok_green"
    param = (
        button("Кол-во Stars", f"admin:boost:{product.id}:e:amount", icon="pencil")
        if product.kind == BoostKind.STARS_PACK.value
        else button("Множитель/часы", f"admin:boost:{product.id}:e:mult", icon="pencil")
    )
    return markup(
        [
            button(toggle, f"admin:boost:{product.id}:tg", icon=toggle_icon),
            button("Удалить", f"admin:boost:{product.id}:del", icon="trash"),
        ],
        [
            button("Название", f"admin:boost:{product.id}:e:title", icon="pencil"),
            button("Описание", f"admin:boost:{product.id}:e:desc", icon="pencil"),
        ],
        [button("Цена XTR", f"admin:boost:{product.id}:e:price", icon="pencil"), param],
        [button("Бусты", "admin:boosts", icon="boost")],
    )


def boost_kinds() -> InlineKeyboardMarkup:
    return markup(
        [button("Пак внутренних Stars", f"admin:boost:new:{BoostKind.STARS_PACK.value}", icon="star")],
        [button("Множитель на время", f"admin:boost:new:{BoostKind.MULTIPLIER.value}", icon="boost")],
        [button("Отмена", "admin:boosts", icon="cross")],
    )


# --- promo --------------------------------------------------------------------------


def promo_home(items: Sequence[PromoCode], page: int, total: int) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                f"{p.code} · +{p.reward} · {p.uses}",
                f"admin:promo:{p.id}",
                icon="ok_green" if p.is_active else "off",
            )
        ]
        for p in items
    ]
    rows.append(pager("admin:promo:list", page, total, PAGE_SIZE))
    rows.append([button("Новый промокод", "admin:promo:new", icon="plus"), _back("admin:catalog")])
    return markup(*rows)


def promo_card(promo: PromoCode) -> InlineKeyboardMarkup:
    toggle = "Выключить" if promo.is_active else "Включить"
    toggle_icon = "off" if promo.is_active else "ok_green"
    return markup(
        [
            button(toggle, f"admin:promo:{promo.id}:tg", icon=toggle_icon),
            button("Удалить", f"admin:promo:{promo.id}:del", icon="trash"),
        ],
        [button("Промокоды", "admin:promo:list:0", icon="promo")],
    )


# --- payments -----------------------------------------------------------------------


def payments_home(items: Sequence[Payment], page: int, total: int) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                f"#{p.id} · {p.xtr_amount} XTR · {p.user_id}",
                f"admin:pay:view:{p.id}",
                icon="undo" if p.status == "refunded" else "check",
            )
        ]
        for p in items
    ]
    rows.append(pager("admin:pay", page, total, PAGE_SIZE))
    rows.append([_back("admin:system")])
    return markup(*rows)


def payment_card(payment: Payment) -> InlineKeyboardMarkup:
    rows = []
    if payment.status != "refunded":
        rows.append([button("Вернуть платёж", f"admin:pay:refund:{payment.id}", icon="undo")])
    rows.append(
        [
            button("Пользователь", f"admin:u:{payment.user_id}", icon="profile"),
            button("Платежи", "admin:pay:0", icon="payments"),
        ]
    )
    return markup(*rows)


def refund_confirm(payment_id: int) -> InlineKeyboardMarkup:
    return markup(
        [button("Да, вернуть", f"admin:pay:refund:{payment_id}:yes", icon="check")],
        [button("Отмена", f"admin:pay:view:{payment_id}", icon="cross")],
    )


# --- settings / providers / channels / admins -----------------------------------------


def settings_home() -> InlineKeyboardMarkup:
    """Root hub: groups only (not every runtime key)."""
    rows: list[list] = []
    row: list = []
    for group_id, label in SETTINGS_GROUP_LABELS.items():
        icon = SETTINGS_GROUP_ICONS.get(group_id, "settings")
        row.append(button(label, f"admin:set:g:{group_id}", icon=icon))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([_back()])
    return markup(*rows)


def settings_group(group_id: str) -> InlineKeyboardMarkup:
    keys = SETTINGS_GROUPS.get(group_id, ())
    rows: list[list] = []
    row: list = []
    for key in keys:
        if key not in RUNTIME_OVERRIDABLE:
            continue
        label = RUNTIME_SETTING_LABELS.get(key, key)[:28]
        row.append(button(label, f"admin:set:{key}", icon="settings"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([button("Все настройки", "admin:set", icon="settings")])
    return markup(*rows)


def setting_edit(key: str, overridden: bool, is_bool: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_bool:
        rows.append(
            [
                button("Включить", f"admin:set:{key}:on", icon="ok_green"),
                button("Выключить", f"admin:set:{key}:off", icon="off"),
            ]
        )
    if overridden:
        rows.append([button("Сбросить к .env", f"admin:set:{key}:reset", icon="undo")])
    group = setting_group(key)
    if group:
        back_label = SETTINGS_GROUP_LABELS.get(group, "Настройки")
        rows.append([button(back_label, f"admin:set:g:{group}", icon="back")])
    else:
        rows.append([button("Настройки", "admin:set", icon="settings")])
    return markup(*rows)


def providers(states: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = [
        [button(PROVIDER_TITLES[name], f"admin:prov:tg:{name}", icon="ok_green" if states.get(name) else "off")]
        for name in CASCADE
    ]
    rows.append(
        [
            button("Трафик", "admin:pf:stats", icon="stats"),
            button("Выданные", "admin:pf:issued:0", icon="upload"),
        ]
    )
    rows.append([button("Засчитанные", "admin:pf:credited:0", icon="check")])
    rows.append([_back()])
    return markup(*rows)


def piarflow_stats() -> InlineKeyboardMarkup:
    return markup(
        [
            button("Выданные", "admin:pf:issued:0", icon="upload"),
            button("Засчитанные", "admin:pf:credited:0", icon="check"),
        ],
        [button("Обновить", "admin:pf:stats", icon="refresh"), button("PiarFlow", "admin:prov", icon="lock")],
    )


def piarflow_list(kind: str, page: int, total: int) -> InlineKeyboardMarkup:
    prefix = f"admin:pf:{kind}"
    return markup(
        pager(prefix, page, total, PAGE_SIZE),
        [button("Трафик", "admin:pf:stats", icon="stats"), button("PiarFlow", "admin:prov", icon="lock")],
    )


def admins(rows_db: Sequence[Admin], can_manage: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_manage:
        rows.extend(
            [[button(f"Удалить {row.user_id}", f"admin:adm:del:{row.user_id}", icon="trash")] for row in rows_db]
        )
        rows.append([button("Добавить админа", "admin:adm:add", icon="plus")])
    rows.append([_back("admin:system")])
    return markup(*rows)


# --- audit / data -------------------------------------------------------------------


def audit(page: int, total: int) -> InlineKeyboardMarkup:
    return markup(pager("admin:audit", page, total, PAGE_SIZE), [_back("admin:system")])


def data_home() -> InlineKeyboardMarkup:
    return markup(
        [
            button("Пользователи CSV", "admin:exp:users", icon="download"),
            button("Выводы CSV", "admin:exp:wd", icon="download"),
        ],
        [
            button("Леджер CSV", "admin:exp:ledger", icon="download"),
            button("Платежи CSV", "admin:exp:pay", icon="download"),
        ],
        [button("Импорт пользователей", "admin:import", icon="upload")],
        [_back("admin:system")],
    )


def ambassadors_hub(pending: int, approved: int) -> InlineKeyboardMarkup:
    return markup(
        [button(f"Очередь ({pending})", "admin:amb:pending", icon="doc")],
        [button(f"Одобренные ({approved})", "admin:amb:list", icon="check")],
        [_back()],
    )


def ambassadors_list(slots: Sequence[AmbassadorSlot], *, back: str = "admin:amb") -> InlineKeyboardMarkup:
    rows = []
    for slot in slots[:20]:
        kind = AMBASSADOR_KIND_LABELS.get(slot.kind, slot.kind)
        rows.append(
            [button(f"#{slot.id} {kind}: {slot.title[:16]}", f"admin:amb:{slot.id}", icon="handshake")]
        )
    rows.append([_back(back)])
    return markup(*rows)


def ambassador_card(slot: AmbassadorSlot) -> InlineKeyboardMarkup:
    rows: list[list] = []
    if slot.status == AmbassadorStatus.PENDING.value:
        rows.append(
            [
                button("Одобрить", f"admin:amb:{slot.id}:ok", icon="check"),
                button("Отклонить", f"admin:amb:{slot.id}:no", icon="cross"),
            ]
        )
    elif slot.status == AmbassadorStatus.APPROVED.value:
        rows.append([button("Изменить условия", f"admin:amb:{slot.id}:edit", icon="pencil")])
        if slot.kind != AmbassadorKind.BOT.value:
            rows.append([button("Chat ID", f"admin:amb:{slot.id}:chat", icon="link")])
            if slot.promo_auto_post:
                rows.append([button("Выкл. автопост", f"admin:amb:{slot.id}:autopost:0", icon="cross")])
            else:
                rows.append([button("Вкл. автопост", f"admin:amb:{slot.id}:autopost:1", icon="megaphone")])
        rows.append([button("Отозвать", f"admin:amb:{slot.id}:revoke", icon="ban")])
    rows.append([_back("admin:amb")])
    return markup(*rows)
