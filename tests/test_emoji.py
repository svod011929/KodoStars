"""Premium emoji helpers and button icon stripping."""

import pytest
from aiogram.enums import MessageEntityType
from aiogram.types import Chat, Message, MessageEntity, User

from app.bot import emoji as pe
from app.bot import texts
from app.bot.utils import button, url_button
from app.config import Settings
from app.services.app_settings import RuntimeSettingsStore, extract_currency_from_message, parse_value
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


def test_premiumize_wraps_emoji_next_to_existing_tags() -> None:
    currency_tag = pe.currency()
    out = pe.premiumize(f"🔥 Баланс: 10 {currency_tag} · 🔒")
    assert '<tg-emoji emoji-id="6041731551845159060">🔥</tg-emoji>' in out
    assert '<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji>' in out
    assert out.count("<tg-emoji") == 3  # the existing tag is kept as is, not nested
    assert pe.premiumize(out) == out


def test_premiumize_only_touches_text_telegram_lets_it_change() -> None:
    fire = '<tg-emoji emoji-id="6041731551845159060">🔥</tg-emoji>'
    gift = pe.html("gift")
    source = (
        '<a href="https://x.y/🔥?q=🎁">ссылка 🔥</a> · <code>🔥</code> · <pre><code class="language-x">🎁</code></pre>'
        " · <b>🔥 <i>🎁</i></b> · <blockquote>🎁</blockquote>"
    )
    out = pe.premiumize(source)
    assert out.startswith('<a href="https://x.y/🔥?q=🎁">ссылка 🔥</a> · <code>🔥</code> · ')
    assert '<pre><code class="language-x">🎁</code></pre>' in out
    assert f"<b>{fire} <i>{gift}</i></b>" in out and f"<blockquote>{gift}</blockquote>" in out
    assert pe.premiumize(out) == out
    assert pe.premiumize("<CODE>🔥</CODE> 🔥") == f"<CODE>🔥</CODE> {fire}"


def test_premiumize_leaves_overridden_currency_fallback_inside_tag() -> None:
    pe.apply_currency("6032644646587338669", "🎁")
    out = pe.premiumize(f"Награда {pe.currency()} и подарок 🎁")
    assert out.count('<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji>') == 2
    assert '<tg-emoji emoji-id="6032644646587338669"><tg-emoji' not in out


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


def test_extract_currency_from_custom_emoji_message() -> None:
    msg = Message(
        message_id=1,
        date=0,
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="A"),
        text="🪙",
        entities=[
            MessageEntity(
                type=MessageEntityType.CUSTOM_EMOJI,
                offset=0,
                length=1,
                custom_emoji_id="6032644646587338669",
            )
        ],
    )
    emoji_id, fallback = extract_currency_from_message(msg)
    assert emoji_id == "6032644646587338669"
    assert fallback == "🪙"


def test_extract_currency_from_plain_text_id() -> None:
    msg = Message(
        message_id=1,
        date=0,
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="A"),
        text="6032644646587338669",
    )
    emoji_id, fallback = extract_currency_from_message(msg)
    assert emoji_id == "6032644646587338669"
    assert fallback is None


@pytest.mark.asyncio
async def test_set_currency_pair_updates_id_and_fallback(session, settings) -> None:
    store = RuntimeSettingsStore(settings)
    saved = await store.set_currency_pair(
        session,
        admin_id=1,
        emoji_id="6032644646587338669",
        fallback="🎁",
    )
    assert saved["currency_emoji_id"] == "6032644646587338669"
    assert saved["currency_emoji_fallback"] == "🎁"
    effective = await store.effective(session)
    assert effective.currency_emoji_id == "6032644646587338669"
    assert pe.currency_id() == "6032644646587338669"
    assert pe.currency_fallback() == "🎁"
