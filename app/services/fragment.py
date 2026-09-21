"""Buy Telegram Stars on Fragment.com and send them to a username.

Uses ``fragment-api-py`` so the wallet mnemonic stays on this server (signed
locally via tonutils). Requires cookies from fragment.com + a free Tonconsole
API key to broadcast the TON payment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.config import Settings
from app.services.errors import EconomyError

log = structlog.get_logger("kodostars.fragment")

try:
    from FragmentAPI import FragmentClient
except ImportError:  # pragma: no cover - optional until deps installed
    FragmentClient = None  # type: ignore[misc, assignment]


class FragmentError(EconomyError):
    pass


@dataclass(slots=True, frozen=True)
class FragmentPurchase:
    username: str
    amount: int
    raw: dict[str, Any]


def parse_cookies(raw: str) -> dict[str, str]:
    """Parse ``stel_ssid=…; stel_token=…`` header-string into a cookie dict."""
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        if key:
            cookies[key] = value.strip()
    return cookies


def require_configured(settings: Settings) -> None:
    if FragmentClient is None:
        raise FragmentError("Пакет fragment-api-py не установлен")
    if not settings.fragment_wallet_mnemonic.strip():
        raise FragmentError("FRAGMENT_WALLET_MNEMONIC не задан в .env")
    if not settings.fragment_cookies.strip():
        raise FragmentError("FRAGMENT_COOKIES не заданы в .env")
    if not settings.fragment_tonapi_key.strip():
        raise FragmentError(
            "FRAGMENT_TONAPI_KEY не задан. Бесплатный ключ: https://tonconsole.com/ (TonAPI)."
        )
    cookies = parse_cookies(settings.fragment_cookies)
    if "stel_ssid" not in cookies or "stel_token" not in cookies:
        raise FragmentError("FRAGMENT_COOKIES должны содержать stel_ssid и stel_token")


def normalize_username(username: str | None) -> str:
    value = (username or "").strip().lstrip("@")
    if not value:
        raise FragmentError("У пользователя нет @username — Fragment не может отправить Stars.")
    return value


async def buy_stars(settings: Settings, *, username: str, amount: int) -> FragmentPurchase:
    """Purchase ``amount`` Stars for ``username`` via Fragment and wait for TX."""
    require_configured(settings)
    assert FragmentClient is not None
    recipient = normalize_username(username)
    if amount < 50:
        raise FragmentError("Минимум покупки на Fragment — 50 Stars")
    cookies = parse_cookies(settings.fragment_cookies)
    log.info("fragment_buy_stars_start", username=recipient, amount=amount)

    try:
        async with FragmentClient(
            cookies=cookies,
            seed=settings.fragment_wallet_mnemonic.strip(),
            api_key=settings.fragment_tonapi_key.strip(),
            wallet_version=settings.fragment_wallet_version,
        ) as client:
            result = await client.purchase_stars(
                recipient,
                amount,
                show_sender=settings.fragment_show_sender,
            )
    except FragmentError:
        raise
    except Exception as exc:
        log.warning("fragment_buy_stars_failed", username=recipient, amount=amount, error=str(exc))
        raise FragmentError(f"Fragment: {exc}") from exc

    if hasattr(result, "model_dump"):
        raw = result.model_dump()
    elif isinstance(result, dict):
        raw = result
    else:
        raw = {"result": str(result)}

    log.info("fragment_buy_stars_ok", username=recipient, amount=amount)
    return FragmentPurchase(username=recipient, amount=amount, raw=raw)
