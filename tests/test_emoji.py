"""Premium emoji helpers and button icon stripping."""

from app.bot import emoji as pe
from app.bot.utils import button, url_button


def test_premiumize_wraps_known_unicode() -> None:
    out = pe.premiumize("Баланс ⭐ и 🔒 замок")
    assert '<tg-emoji emoji-id="5904462880941545555">⭐</tg-emoji>' in out
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
