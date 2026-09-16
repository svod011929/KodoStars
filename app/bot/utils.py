"""Small Telegram helpers shared by handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

PAGE_SIZE = 8


def h(value: object) -> str:
    """HTML-escape any value for safe interpolation into messages."""
    return escape(str(value), quote=False)


def fmt_dt(value: datetime | None, *, with_time: bool = True) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.strftime("%d.%m.%Y %H:%M") if with_time else value.strftime("%d.%m.%Y")


def fmt_ago(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - value
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "только что"
    if seconds < 3600:
        return f"{seconds // 60} мин назад"
    if seconds < 86400:
        return f"{seconds // 3600} ч назад"
    return f"{seconds // 86400} дн назад"


def fmt_duration(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    return f"{minutes} мин"


def fmt_signed(amount: int) -> str:
    return f"+{amount}" if amount > 0 else str(amount)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{h(name)}</a>'


def parse_id(data: str | None, index: int = -1, default: int = 0) -> int:
    parts = (data or "").split(":")
    try:
        return int(parts[index])
    except (ValueError, IndexError):
        return default


async def safe_edit(
    message: Message | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    disable_web_page_preview: bool = True,
) -> None:
    """Edit in place; fall back to a new message when the original cannot be edited."""
    if message is None:
        return
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as exc:
        lowered = str(exc).lower()
        if "message is not modified" in lowered:
            return
        if "there is no text in the message" in lowered or "can't be edited" in lowered:
            await message.answer(
                text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview
            )
            return
        raise


async def safe_answer(call: CallbackQuery, text: str | None = None, *, alert: bool = False) -> None:
    try:
        await call.answer(text, show_alert=alert)
    except TelegramBadRequest:
        # Query is too old or already answered — nothing to do.
        return


def pager(prefix: str, page: int, total: int, page_size: int = PAGE_SIZE) -> list[InlineKeyboardButton]:
    """Build a «‹ page/pages ›» row for ``callback_data`` ``f"{prefix}:{page}"``."""
    pages = max((total + page_size - 1) // page_size, 1)
    page = min(max(page, 0), pages - 1)
    row: list[InlineKeyboardButton] = []
    if pages <= 1:
        return row
    row.append(
        InlineKeyboardButton(text="‹", callback_data=f"{prefix}:{max(page - 1, 0)}")
        if page > 0
        else InlineKeyboardButton(text="·", callback_data="noop")
    )
    row.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    row.append(
        InlineKeyboardButton(text="›", callback_data=f"{prefix}:{min(page + 1, pages - 1)}")
        if page < pages - 1
        else InlineKeyboardButton(text="·", callback_data="noop")
    )
    return row


def button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def url_button(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def markup(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])
