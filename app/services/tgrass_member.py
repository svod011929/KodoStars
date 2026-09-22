"""Tgrass traffic-buy membership check.

@tgrassbot → «Проверка подписки через API» sends:

``GET {url}?telegram_id=123&api_key=KEY``

and expects ``{"is_member": true|false}``.

A start alone is not a subscription: ``is_member`` is true only after the user
has passed the OP gate (``last_op_ok_at``) and is still in the bot.
"""

from __future__ import annotations

import hmac

from app.db.models import User


def is_traffic_member(user: User | None) -> bool:
    """Whether a bought click should count as subscribed to this bot."""
    if user is None or user.is_banned or user.blocked_bot_at is not None:
        return False
    return user.last_op_ok_at is not None


def member_key_matches(expected: str, provided: str | None) -> bool:
    """Empty expected key means Tgrass may call without ``api_key``."""
    secret = expected.strip()
    if not secret:
        return True
    got = (provided or "").strip()
    if len(got) != len(secret):
        return False
    return hmac.compare_digest(got, secret)
