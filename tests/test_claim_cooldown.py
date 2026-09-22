"""Claim cooldown must ignore presence stamps from upsert_user."""

from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.db.models import User
from app.services import antifraud
from app.services.errors import CooldownActive


@pytest.fixture(autouse=True)
def _clear_cooldowns() -> None:
    antifraud.clear_earn_cooldowns()
    yield
    antifraud.clear_earn_cooldowns()


def test_cooldown_ignores_fresh_last_action_at_from_upsert() -> None:
    """Reproduce the production bug: middleware stamps last_action_at on every click."""
    settings = Settings(
        bot_token="000000000:PLACEHOLDER_TOKEN_REPLACE_ME",
        admin_ids_raw="1",
        claim_cooldown_seconds=3,
    )
    user = User(id=42, first_name="A", last_action_at=datetime.now(UTC))
    # Must NOT raise — presence stamp alone is not an earn action.
    antifraud.ensure_action_cooldown(user, settings)


def test_cooldown_blocks_after_earn_then_allows() -> None:
    settings = Settings(
        bot_token="000000000:PLACEHOLDER_TOKEN_REPLACE_ME",
        admin_ids_raw="1",
        claim_cooldown_seconds=10,
    )
    user = User(id=7, first_name="A")
    antifraud.note_earn_action(user.id)
    with pytest.raises(CooldownActive, match="Подождите"):
        antifraud.ensure_action_cooldown(user, settings)

    # Simulate wait by backdating the mono clock entry.
    antifraud._last_earn_mono[user.id] = antifraud._last_earn_mono[user.id] - 11.0
    antifraud.ensure_action_cooldown(user, settings)


def test_cooldown_disabled_when_zero() -> None:
    settings = Settings(
        bot_token="000000000:PLACEHOLDER_TOKEN_REPLACE_ME",
        admin_ids_raw="1",
        claim_cooldown_seconds=0,
    )
    user = User(id=1, first_name="A")
    antifraud.note_earn_action(user.id)
    antifraud.ensure_action_cooldown(user, settings)
