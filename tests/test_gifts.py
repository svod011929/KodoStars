"""Gift catalog filtering for withdrawal offers."""

from aiogram.enums import StickerType
from aiogram.types import Gift, Sticker

from app.config import Settings
from app.services.gifts import filter_offers, gift_to_offer, invalidate_cache


def _gift(gift_id: str, stars: int, *, emoji: str = "🎁", premium: bool = False, remaining: int | None = None) -> Gift:
    return Gift(
        id=gift_id,
        sticker=Sticker(
            file_id=f"f{gift_id}",
            file_unique_id=f"u{gift_id}",
            type=StickerType.REGULAR,
            width=100,
            height=100,
            is_animated=False,
            is_video=False,
            emoji=emoji,
        ),
        star_count=stars,
        is_premium=premium or None,
        remaining_count=remaining,
    )


def test_filter_offers_by_balance_limits_and_premium() -> None:
    invalidate_cache()
    settings = Settings(
        bot_token="000000000:PLACEHOLDER_TOKEN_REPLACE_ME",
        admin_ids_raw="1",
        withdraw_min=50,
        withdraw_max=200,
    )
    catalog = [
        _gift("cheap", 15, emoji="🍬"),
        _gift("ok", 50, emoji="🧸"),
        _gift("mid", 100, emoji="🌹"),
        _gift("high", 250, emoji="🏆"),
        _gift("prem", 75, emoji="💎", premium=True),
        _gift("gone", 60, emoji="❌", remaining=0),
    ]
    offers = filter_offers(catalog, balance=120, settings=settings, is_premium=False)
    assert [(o.id, o.star_count, o.emoji) for o in offers] == [
        ("ok", 50, "🧸"),
        ("mid", 100, "🌹"),
    ]
    premium_offers = filter_offers(catalog, balance=120, settings=settings, is_premium=True)
    assert {o.id for o in premium_offers} == {"ok", "mid", "prem"}


def test_gift_to_offer_falls_back_emoji() -> None:
    bare = Gift(
        id="x",
        sticker=Sticker(
            file_id="f",
            file_unique_id="u",
            type=StickerType.REGULAR,
            width=1,
            height=1,
            is_animated=False,
            is_video=False,
        ),
        star_count=50,
    )
    assert gift_to_offer(bare).emoji == "🎁"
