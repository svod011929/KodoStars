"""Premium emoji helpers and button icon stripping."""

import pytest

from app.bot import emoji as pe
from app.bot.utils import button, url_button
from app.config import Settings
from app.services.app_settings import parse_value
from app.services.errors import ValidationError


@pytest.fixture(autouse=True)
def _reset_currency() -> None:
    pe.apply_currency(pe.DEFAULT_CURRENCY_ID, pe.DEFAULT_CURRENCY_FALLBACK)
    yield
    pe.apply_currency(pe.DEFAULT_CURRENCY_ID, pe.DEFAULT_CURRENCY_FALLBACK)


def test_premiumize_wraps_known_unicode() -> None:
    out = pe.premiumize("Баланс ⭐ и 🔒 замок")
    assert f'<tg-emoji emoji-id="{pe.DEFAULT_CURRENCY_ID}">⭐</tg-emoji>' in out
    assert '<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji>' in out
    assert pe.premiumize(out) == out  # idempotent once tagged


def test_split_icon_strips_leading_emoji() -> None:
    label, icon = pe.split_icon("👤 Профиль")
    assert label == "Профиль"
    assert icon == pe.id_of("profile")


def test_button_uses_icon_custom_emoji_id() -> None:
    btn = button("Профиль", "menu:profile", icon="profile")
    assert btn.text == "Профиль"
    assert btn.icon_custom_emoji_id == pe.id_of("profile")
    assert "👤" not in btn.text

    auto = button("🎁 Ежедневка", "menu:daily")
    assert auto.text == "Ежедневка"
    assert auto.icon_custom_emoji_id == pe.id_of("gift")


def test_url_button_premium_icon() -> None:
    btn = url_button("Подписаться", "https://t.me/x", icon="clip")
    assert btn.text == "Подписаться"
    assert btn.icon_custom_emoji_id == pe.id_of("clip")


def test_currency_override_changes_star_and_premiumize() -> None:
    pe.apply_currency("6032644646587338669", "🎁")
    assert pe.star() == '<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji>'
    assert pe.id_of("star") == "6032644646587338669"
    assert pe.currency_fallback() == "🎁"
    out = pe.premiumize("Баланс ⭐")
    assert "6032644646587338669" in out
    btn = button("Вывод", "menu:withdraw", icon="star")
    assert btn.icon_custom_emoji_id == "6032644646587338669"


def test_star_proxy_reads_live_override() -> None:
    from app.bot import texts

    pe.apply_currency("1111111111111111111", "💫")
    assert "1111111111111111111" in str(texts.STAR)
    assert "💫" in str(texts.STAR)


def test_parse_currency_emoji_id_accepts_digits_and_tg_tag() -> None:
    assert parse_value("currency_emoji_id", "6032644646587338669") == "6032644646587338669"
    assert (
        parse_value(
            "currency_emoji_id",
            '<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji>',
        )
        == "6032644646587338669"
    )
    with pytest.raises(ValidationError):
        parse_value("currency_emoji_id", "not-an-id")


def test_settings_currency_defaults() -> None:
    s = Settings(admin_ids_raw="1", database_url="sqlite+aiosqlite://")
    assert s.currency_emoji_id == pe.DEFAULT_CURRENCY_ID
    assert s.currency_emoji_fallback == "⭐"
