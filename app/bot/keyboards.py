from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import BoostProduct, Task, Withdrawal
from app.op.base import Sponsor


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Профиль", callback_data="menu:profile"),
            InlineKeyboardButton(text="Рефералы", callback_data="menu:refs"),
        ],
        [
            InlineKeyboardButton(text="Ежедневка", callback_data="menu:daily"),
            InlineKeyboardButton(text="Задания", callback_data="menu:tasks"),
        ],
        [
            InlineKeyboardButton(text="Бусты", callback_data="menu:boosts"),
            InlineKeyboardButton(text="Вывод", callback_data="menu:withdraw"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="Админка", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="menu:home")]]
    )


def op_keyboard(sponsors: list[Sponsor]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for sponsor in sponsors:
        title = sponsor.title[:32] or "Спонсор"
        row.append(InlineKeyboardButton(text=title, url=sponsor.url))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Я подписался", callback_data="op:verify")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tasks_keyboard(tasks: list[Task], done: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for task in tasks:
        mark = "✓ " if task.id in done else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{task.title} · +{task.reward}⭐",
                    callback_data=f"task:do:{task.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def boosts_keyboard(products: list[BoostProduct]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{product.title} · {product.xtr_price} XTR",
                callback_data=f"boost:buy:{product.id}",
            )
        ]
        for product in products
    ]
    rows.append([InlineKeyboardButton(text="В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def withdraw_keyboard(balance: int, minimum: int) -> InlineKeyboardMarkup:
    options = [value for value in (minimum, 100, 250) if value <= balance]
    rows = []
    chunk: list[InlineKeyboardButton] = []
    for value in options:
        chunk.append(InlineKeyboardButton(text=f"{value} ⭐", callback_data=f"wd:amt:{value}"))
        if len(chunk) == 3:
            rows.append(chunk)
            chunk = []
    if chunk:
        rows.append(chunk)
    if balance >= minimum:
        rows.append(
            [InlineKeyboardButton(text=f"Всё ({balance} ⭐)", callback_data=f"wd:amt:{balance}")]
        )
    rows.append([InlineKeyboardButton(text="В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Статистика", callback_data="admin:stats"),
                InlineKeyboardButton(text="Выводы", callback_data="admin:wd"),
            ],
            [
                InlineKeyboardButton(text="Провайдеры", callback_data="admin:prov"),
                InlineKeyboardButton(text="Рассылка", callback_data="admin:bc"),
            ],
            [
                InlineKeyboardButton(text="Бан", callback_data="admin:ban"),
                InlineKeyboardButton(text="Разбан", callback_data="admin:unban"),
            ],
            [
                InlineKeyboardButton(
                    text="Импорт пользователей", callback_data="admin:import"
                )
            ],
            [InlineKeyboardButton(text="В меню", callback_data="menu:home")],
        ]
    )


def admin_wd_list(items: list[Withdrawal]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"#{item.id} · {item.amount}⭐ · {item.status}",
                callback_data=f"admin:wd:view:{item.id}",
            )
        ]
        for item in items
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_wd_view(wd_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Согласовать", callback_data=f"admin:wd:ok:{wd_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"admin:wd:no:{wd_id}"),
            ],
            [
                InlineKeyboardButton(
                    text="Подтвердить отправку",
                    callback_data=f"admin:wd:sent:{wd_id}",
                )
            ],
            [InlineKeyboardButton(text="К очереди", callback_data="admin:wd")],
        ]
    )


def admin_providers(states: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'ON' if enabled else 'OFF'} · {name}",
                callback_data=f"admin:prov:tg:{name}",
            )
        ]
        for name, enabled in states.items()
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
