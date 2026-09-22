"""Runtime settings stored in the ``app_settings`` table.

Only keys listed in ``RUNTIME_OVERRIDABLE`` can be changed. Values are validated by
building a full ``Settings`` model, so the same constraints apply as for ``.env``.
"""

from __future__ import annotations

import re
from typing import Any

from aiogram.enums import MessageEntityType
from aiogram.types import Message
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import emoji as pe
from app.config import RUNTIME_OVERRIDABLE, Settings
from app.db.models import AppSetting
from app.services.errors import ValidationError

_TRUE = {"1", "true", "on", "yes", "да", "вкл", "включить", "y"}
_FALSE = {"0", "false", "off", "no", "нет", "выкл", "выключить", "n"}


def extract_currency_from_message(message: Message) -> tuple[str | None, str | None]:
    """Pull ``(custom_emoji_id, unicode_fallback)`` from an admin paste.

    Telegram premium emoji arrive as a unicode fallback in ``text`` plus a
    ``custom_emoji`` entity with the numeric id. Plain numeric text is treated
    as an id-only update (fallback unchanged).
    """
    text = (message.text or message.caption or "").strip()
    emoji_id: str | None = None
    fallback: str | None = None

    for ent in message.entities or ():
        if ent.type == MessageEntityType.CUSTOM_EMOJI and ent.custom_emoji_id:
            emoji_id = str(ent.custom_emoji_id)
            # Entity covers the fallback grapheme(s) in UTF-16 offsets; use full text.
            fallback = text or None
            break

    if emoji_id is None and text:
        match = re.search(r'emoji-id=["\']?(\d+)', text)
        if match:
            emoji_id = match.group(1)
            inner = re.search(r"<tg-emoji[^>]*>([^<]+)</tg-emoji>", text)
            fallback = inner.group(1) if inner else None
        elif text.isdigit():
            emoji_id = text
        else:
            fallback = text[:8]

    return emoji_id, fallback


def parse_value(key: str, raw: str) -> Any:
    kind = RUNTIME_OVERRIDABLE.get(key)
    if kind is None:
        raise ValidationError("Эту настройку нельзя менять из бота")
    text = raw.strip()
    if kind is bool:
        low = text.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValidationError("Введите «вкл» или «выкл»")
    if kind is int:
        if not text.lstrip("-").isdigit():
            raise ValidationError("Нужно целое число")
        return int(text)
    if key == "currency_emoji_id":
        match = re.search(r'emoji-id=["\']?(\d+)', text)
        if match:
            return match.group(1)
        if text.isdigit():
            return text
        raise ValidationError(
            "Пришлите numeric emoji-id или кусок "
            '<tg-emoji emoji-id="…">…</tg-emoji>'
        )
    if key == "currency_emoji_fallback":
        if not text:
            raise ValidationError("Нужен unicode-символ для fallback (например ⭐)")
        # One grapheme / short token — strip accidental tg-emoji wrappers' inner char.
        inner = re.search(r"<tg-emoji[^>]*>([^<]+)</tg-emoji>", text)
        return (inner.group(1) if inner else text)[:8]
    return text


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "вкл" if value else "выкл"
    if value is None or value == "":
        return "—"
    return str(value)


class RuntimeSettingsStore:
    def __init__(self, base: Settings) -> None:
        self._base = base
        self._cache: dict[str, Any] | None = None

    @property
    def base(self) -> Settings:
        return self._base

    def invalidate(self) -> None:
        self._cache = None

    async def overrides(self, session: AsyncSession) -> dict[str, Any]:
        if self._cache is None:
            result = await session.execute(select(AppSetting))
            loaded: dict[str, Any] = {}
            for row in result.scalars().all():
                if row.key in RUNTIME_OVERRIDABLE and isinstance(row.value, dict):
                    loaded[row.key] = row.value.get("v")
            self._cache = loaded
        return dict(self._cache)

    async def effective(self, session: AsyncSession) -> Settings:
        overrides = await self.overrides(session)
        settings = self._base.with_overrides(overrides)
        pe.apply_currency(settings.currency_emoji_id, settings.currency_emoji_fallback)
        return settings

    async def set(self, session: AsyncSession, *, key: str, raw: str, admin_id: int) -> Any:
        value = parse_value(key, raw)
        current = await self.overrides(session)
        candidate = {**current, key: value}
        _validate(self._base, candidate)
        row = await session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value={"v": value}, updated_by=admin_id)
            session.add(row)
        else:
            row.value = {"v": value}
            row.updated_by = admin_id
        await session.flush()
        self._cache = candidate
        settings = self._base.with_overrides(candidate)
        pe.apply_currency(settings.currency_emoji_id, settings.currency_emoji_fallback)
        return value

    async def set_currency_pair(
        self,
        session: AsyncSession,
        *,
        admin_id: int,
        emoji_id: str | None = None,
        fallback: str | None = None,
    ) -> dict[str, Any]:
        """Update currency id and/or fallback together (one admin paste)."""
        if not emoji_id and not fallback:
            raise ValidationError("Пришлите премиум-эмодзи или numeric id")
        current = await self.overrides(session)
        candidate = dict(current)
        saved: dict[str, Any] = {}
        if emoji_id:
            value = parse_value("currency_emoji_id", emoji_id)
            candidate["currency_emoji_id"] = value
            saved["currency_emoji_id"] = value
        if fallback:
            value = parse_value("currency_emoji_fallback", fallback)
            candidate["currency_emoji_fallback"] = value
            saved["currency_emoji_fallback"] = value
        _validate(self._base, candidate)
        for key, value in saved.items():
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value={"v": value}, updated_by=admin_id))
            else:
                row.value = {"v": value}
                row.updated_by = admin_id
        await session.flush()
        self._cache = candidate
        settings = self._base.with_overrides(candidate)
        pe.apply_currency(settings.currency_emoji_id, settings.currency_emoji_fallback)
        return saved

    async def reset(self, session: AsyncSession, *, key: str) -> None:
        if key not in RUNTIME_OVERRIDABLE:
            raise ValidationError("Эту настройку нельзя менять из бота")
        row = await session.get(AppSetting, key)
        if row is not None:
            await session.delete(row)
            await session.flush()
        if self._cache is not None:
            self._cache.pop(key, None)
        settings = self._base.with_overrides(self._cache or {})
        pe.apply_currency(settings.currency_emoji_id, settings.currency_emoji_fallback)

    def default_value(self, key: str) -> Any:
        return getattr(self._base, key)


def _validate(base: Settings, overrides: dict[str, Any]) -> None:
    data = base.model_dump()
    data.update(overrides)
    try:
        Settings.model_validate(data)
    except PydanticValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        raise ValidationError(str(first.get("msg", "Некорректное значение"))) from exc
