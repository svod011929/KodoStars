"""Bot display name: live override + ``{bot}`` placeholder expansion."""

from app.bot import brand
from app.bot import texts


def _reset() -> None:
    brand.apply_bot_name(brand.DEFAULT_BOT_NAME)


def setup_function() -> None:
    _reset()


def teardown_function() -> None:
    _reset()


def test_default_bot_name() -> None:
    assert brand.bot_name() == "KodoStars"
    assert str(texts.BOT) == "KodoStars"


def test_apply_bot_name_updates_live_value() -> None:
    brand.apply_bot_name("MyCoolBot")
    assert brand.bot_name() == "MyCoolBot"
    assert str(texts.BOT) == "MyCoolBot"


def test_apply_bot_name_strips_and_falls_back() -> None:
    brand.apply_bot_name("  StarsEarn  ")
    assert brand.bot_name() == "StarsEarn"
    brand.apply_bot_name("")
    assert brand.bot_name() == brand.DEFAULT_BOT_NAME
    brand.apply_bot_name("   ")
    assert brand.bot_name() == brand.DEFAULT_BOT_NAME


def test_expand_replaces_bot_placeholder() -> None:
    brand.apply_bot_name("NovaStars")
    assert brand.expand("Добро пожаловать в {bot}!") == "Добро пожаловать в NovaStars!"
    assert brand.expand("{bot} · {bot}") == "NovaStars · NovaStars"
    assert brand.expand("без плейсхолдера") == "без плейсхолдера"
    assert brand.expand("") == ""
    assert brand.expand(None) is None  # type: ignore[arg-type]


def test_home_and_share_use_live_bot_name() -> None:
    from app.db.models import User
    from app.services.levels import LevelInfo

    brand.apply_bot_name("AcmeStars")
    user = User(id=1, first_name="Dan", xp=0)
    level = LevelInfo(level=1, min_xp=0, multiplier_bp=100, next_level=2, next_xp=100)
    home = texts.home(user, balance=0, held=0, level=level, boost_bp=100, boost_until=None, link="https://t.me/x")
    assert "AcmeStars" in home
    assert "KodoStars" not in home
    hooked_home = texts.home(
        user, balance=0, held=0, level=level, boost_bp=100, boost_until=None, link="https://t.me/x", l1_bonus=10
    )
    assert "за каждого друга" in hooked_home

    share = texts.share_text("https://t.me/x", signup_bonus=0)
    assert "AcmeStars" in share
    assert "KodoStars" not in share

    hooked = texts.share_text("https://t.me/x", signup_bonus=0, l1_bonus=10)
    assert "AcmeStars" in hooked
    assert "10" in hooked
    assert "KodoStars" not in hooked


def test_premiumize_expands_bot_placeholder() -> None:
    from app.bot import emoji as pe

    brand.apply_bot_name("LiveBot")
    out = pe.premiumize("Привет из {bot}")
    assert "LiveBot" in out
    assert "{bot}" not in out
