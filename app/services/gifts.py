"""Telegram gift catalog for withdrawal payouts.

Users pick a ready gift instead of typing an arbitrary Stars amount. Prices come
from ``getAvailableGifts`` (``star_count``); the bot pays them out later via
``sendGift`` after an admin confirms the request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Gift

from app.config import Settings

log = structlog.get_logger("kodostars.gifts")

_CACHE_TTL_SEC = 300.0
_cache_gifts: list[Gift] = []
_cache_expires_at = 0.0

GIFTS_PER_PAGE = 8


@dataclass(frozen=True, slots=True)
class GiftOffer:
    id: str
    star_count: int
    emoji: str
    is_premium: bool


def invalidate_cache() -> None:
    global _cache_gifts, _cache_expires_at
    _cache_gifts = []
    _cache_expires_at = 0.0


def _emoji_of(gift: Gift) -> str:
    sticker = gift.sticker
    if sticker is not None and sticker.emoji:
        return sticker.emoji
    return "🎁"


def gift_to_offer(gift: Gift) -> GiftOffer:
    return GiftOffer(
        id=str(gift.id),
        star_count=int(gift.star_count),
        emoji=_emoji_of(gift),
        is_premium=bool(gift.is_premium),
    )


def _is_available(gift: Gift) -> bool:
    if gift.remaining_count is not None and gift.remaining_count <= 0:
        return False
    if gift.personal_remaining_count is not None and gift.personal_remaining_count <= 0:
        return False
    return True


async def fetch_catalog(bot: Bot, *, force: bool = False) -> list[Gift]:
    global _cache_gifts, _cache_expires_at
    now = time.monotonic()
    if not force and _cache_gifts and now < _cache_expires_at:
        return list(_cache_gifts)
    try:
        response = await bot.get_available_gifts()
    except TelegramAPIError as exc:
        log.warning("gifts.catalog_failed", error=str(exc))
        if _cache_gifts:
            return list(_cache_gifts)
        raise
    gifts = [g for g in (response.gifts or []) if _is_available(g)]
    gifts.sort(key=lambda g: (g.star_count, g.id))
    _cache_gifts = gifts
    _cache_expires_at = now + _CACHE_TTL_SEC
    return list(gifts)


def filter_offers(
    gifts: list[Gift],
    *,
    balance: int,
    settings: Settings,
    is_premium: bool,
) -> list[GiftOffer]:
    maximum = settings.withdraw_max if settings.withdraw_max else None
    offers: list[GiftOffer] = []
    for gift in gifts:
        if not _is_available(gift):
            continue
        if gift.is_premium and not is_premium:
            continue
        price = int(gift.star_count)
        if price < settings.withdraw_min:
            continue
        if maximum and price > maximum:
            continue
        if price > balance:
            continue
        offers.append(gift_to_offer(gift))
    return offers


async def list_affordable(
    bot: Bot,
    *,
    balance: int,
    settings: Settings,
    is_premium: bool,
) -> list[GiftOffer]:
    catalog = await fetch_catalog(bot)
    return filter_offers(catalog, balance=balance, settings=settings, is_premium=is_premium)


async def resolve_offer(bot: Bot, gift_id: str) -> GiftOffer | None:
    catalog = await fetch_catalog(bot)
    for gift in catalog:
        if str(gift.id) == gift_id and _is_available(gift):
            return gift_to_offer(gift)
    return None
