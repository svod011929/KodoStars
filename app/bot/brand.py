"""Live bot display name (Telegram ``get_me().first_name``) for UI texts.

Texts may use the ``BOT`` glyph (``str`` → current name) or the ``{bot}``
placeholder. Outbound messages expand ``{bot}`` in ``premiumize``.
"""

from __future__ import annotations

DEFAULT_BOT_NAME = "KodoStars"

_bot_name: str = DEFAULT_BOT_NAME

PLACEHOLDER = "{bot}"


def apply_bot_name(name: str | None) -> None:
    """Set the live bot title used in messages (falls back to ``DEFAULT_BOT_NAME``)."""
    global _bot_name
    cleaned = (name or "").strip()
    _bot_name = cleaned or DEFAULT_BOT_NAME


def bot_name() -> str:
    return _bot_name


def expand(text: str | None) -> str | None:
    """Replace ``{bot}`` with the live display name. Passes ``None`` through."""
    if text is None:
        return None
    if PLACEHOLDER not in text:
        return text
    return text.replace(PLACEHOLDER, _bot_name)
