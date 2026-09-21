"""Buy Telegram Stars on Fragment.com and send them to a username.

Uses ``fragment-api-py`` so the wallet mnemonic stays on this server (signed
locally via tonutils). Payment broadcast goes through Toncenter:

* with ``FRAGMENT_TONAPI_KEY`` — TonAPI (tonconsole.com) or Toncenter key;
* without it — public Toncenter (no key), same as many bots that only keep
  mnemonic + Fragment cookies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from ton_core import NetworkGlobalID
from tonutils.clients import TonapiClient, ToncenterClient

from app.config import Settings
from app.services.errors import EconomyError

log = structlog.get_logger("kodostars.fragment")

try:
    from FragmentAPI import FragmentClient
    from FragmentAPI.utils import wallet as fragment_wallet
except ImportError:  # pragma: no cover - optional until deps installed
    FragmentClient = None  # type: ignore[misc, assignment]
    fragment_wallet = None  # type: ignore[misc, assignment]

# Sentinel passed into FragmentClient when we intentionally use keyless Toncenter.
_PUBLIC_TONCENTER = "public"


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
    cookies = parse_cookies(settings.fragment_cookies)
    if "stel_ssid" not in cookies or "stel_token" not in cookies:
        raise FragmentError("FRAGMENT_COOKIES должны содержать stel_ssid и stel_token")


def normalize_username(username: str | None) -> str:
    value = (username or "").strip().lstrip("@")
    if not value:
        raise FragmentError("У пользователя нет @username — Fragment не может отправить Stars.")
    return value


def _make_ton_client(client: Any) -> Any:
    """Prefer Toncenter; allow keyless public access when no real API key is set."""
    key = getattr(client, "api_key", None)
    if key in (None, "", _PUBLIC_TONCENTER):
        key = None
    provider = getattr(client, "api_provider", "toncenter")
    if provider == "tonapi" and key:
        return TonapiClient(network=NetworkGlobalID.MAINNET, api_key=key)
    return ToncenterClient(network=NetworkGlobalID.MAINNET, api_key=key)


async def buy_stars(settings: Settings, *, username: str, amount: int) -> FragmentPurchase:
    """Purchase ``amount`` Stars for ``username`` via Fragment and wait for TX."""
    require_configured(settings)
    assert FragmentClient is not None and fragment_wallet is not None
    recipient = normalize_username(username)
    if amount < 50:
        raise FragmentError("Минимум покупки на Fragment — 50 Stars")
    cookies = parse_cookies(settings.fragment_cookies)

    tonapi = settings.fragment_tonapi_key.strip()
    if tonapi:
        api_key = tonapi
        api_provider = "tonapi"
    else:
        # fragment-api-py requires a non-empty api_key string; we swap the HTTP
        # client for keyless Toncenter so no tonconsole account is needed.
        api_key = _PUBLIC_TONCENTER
        api_provider = "toncenter"

    log.info(
        "fragment_buy_stars_start",
        username=recipient,
        amount=amount,
        provider=api_provider,
        keyed=bool(tonapi),
    )

    original_factory = fragment_wallet._make_ton_client
    fragment_wallet._make_ton_client = _make_ton_client  # type: ignore[assignment]
    try:
        async with FragmentClient(
            cookies=cookies,
            seed=settings.fragment_wallet_mnemonic.strip(),
            api_key=api_key,
            api_provider=api_provider,
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
    finally:
        fragment_wallet._make_ton_client = original_factory  # type: ignore[assignment]

    if hasattr(result, "model_dump"):
        raw = result.model_dump()
    elif isinstance(result, dict):
        raw = result
    else:
        raw = {"result": str(result)}

    log.info("fragment_buy_stars_ok", username=recipient, amount=amount)
    return FragmentPurchase(username=recipient, amount=amount, raw=raw)
