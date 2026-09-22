"""Referral activation copy is clear and follows runtime settings."""

from app.bot import texts
from app.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        bot_token="000000000:PLACEHOLDER_TOKEN_REPLACE_ME",
        admin_ids_raw="1",
        min_referral_activity=2,
        referral_min_piarflow_subs=2,
        device_check_enabled=False,
        web_public_url="",
    )
    base.update(overrides)
    return Settings(**base)


def test_referral_activation_rules_checklist() -> None:
    settings = _settings()
    rules = texts.referral_activation_rules(settings)
    joined = "\n".join(rules)
    assert "твоей" in joined.lower() or "твоей" in joined
    assert "2" in joined and "действи" in joined
    assert "спонсор" in joined
    assert "PiarFlow" not in joined  # user-facing: no jargon


def test_referral_screen_has_sections() -> None:
    from app.db.models import User

    settings = _settings()
    user = User(id=1, first_name="A")
    body = texts.referrals(
        user,
        link="https://t.me/bot?start=ref_1",
        stats={1: 0, 2: 0},
        activated_l1=0,
        earned=0,
        rank=None,
        settings=settings,
        recent=[],
    )
    assert "Когда друг считается активным" in body
    assert "Что ты получаешь" in body
    assert "ещё не активирован" in body


def test_rules_omit_device_when_disabled() -> None:
    settings = _settings(device_check_enabled=False, web_public_url="")
    assert settings.device_check_active is False
    joined = "\n".join(texts.referral_activation_rules(settings))
    assert "Подтвердить устройство" not in joined


def test_rules_include_device_when_active() -> None:
    settings = _settings(device_check_enabled=True, web_public_url="https://example.com")
    assert settings.device_check_active is True
    joined = "\n".join(texts.referral_activation_rules(settings))
    assert "Подтвердить устройство" in joined
