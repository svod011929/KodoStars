"""BotoHub Views — paid ad impressions (not OP).

Docs: https://views.botohub.me/integration

``POST /ad/SendPost`` with raw ``Authorization`` token (no Bearer).
``hi: true`` only for first ``/start``; regular ads after earn actions.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

import structlog

from app.config import Settings
from app.op import http as op_http

log = structlog.get_logger("kodostars.botohub_views")

_RESULT_NAMES = {
    1: "Success",
    2: "RevokedTokenError",
    3: "UserForbiddenError",
    4: "ToManyRequestsError",
    5: "OtherBotApiError",
    6: "OtherError",
    7: "AdLimited",
    8: "NoAds",
    9: "BotIsNotEnabled",
    10: "Banned",
    11: "InReview",
}

_last_ad_mono: OrderedDict[int, float] = OrderedDict()
_MAX_AD_TRACKED = 50_000


def clear_ad_cooldowns() -> None:
    """Test helper."""
    _last_ad_mono.clear()


def _note_ad_shown(user_id: int) -> None:
    _last_ad_mono[user_id] = time.monotonic()
    _last_ad_mono.move_to_end(user_id)
    while len(_last_ad_mono) > _MAX_AD_TRACKED:
        _last_ad_mono.popitem(last=False)


def _cooldown_active(user_id: int, settings: Settings) -> bool:
    wait = int(settings.botohub_views_cooldown_seconds)
    if wait <= 0:
        return False
    last = _last_ad_mono.get(user_id)
    if last is None:
        return False
    return (time.monotonic() - last) < float(wait)


def _configured(settings: Settings) -> bool:
    return bool(settings.botohub_views_enabled and settings.botohub_views_token.strip())


async def send_post(user_id: int, settings: Settings, *, hi: bool = False) -> bool:
    """Call BotoHub SendPost. Returns True only on ``SendPostResult == 1``."""
    if not _configured(settings):
        return False
    url = (settings.botohub_views_api_url or "").strip() or "https://views.botohub.me/ad/SendPost"
    token = settings.botohub_views_token.strip()
    try:
        status, payload = await op_http.post_json(
            url,
            json={"SendToChatId": int(user_id), "hi": bool(hi)},
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
            },
            timeout_sec=float(settings.op_timeout_sec),
        )
    except Exception:
        log.warning("botohub_views_http_error", user_id=user_id, hi=hi, exc_info=True)
        return False

    data = op_http.as_dict(payload)
    result = data.get("SendPostResult")
    ok = status == 200 and result == 1
    if ok:
        log.info("botohub_views_sent", user_id=user_id, hi=hi)
        return True
    log.info(
        "botohub_views_skip",
        user_id=user_id,
        hi=hi,
        http_status=status,
        result=result,
        result_name=_RESULT_NAMES.get(result if isinstance(result, int) else -1, "Unknown"),
    )
    return False


async def maybe_send_hi(user_id: int, settings: Settings) -> bool:
    """Welcome impression for a brand-new user (first /start)."""
    return await send_post(user_id, settings, hi=True)


async def maybe_send_ad(user_id: int, settings: Settings) -> bool:
    """Regular impression after a useful earn action; respects local cooldown."""
    if not _configured(settings):
        return False
    if _cooldown_active(user_id, settings):
        log.debug("botohub_views_cooldown", user_id=user_id)
        return False
    ok = await send_post(user_id, settings, hi=False)
    if ok:
        _note_ad_shown(user_id)
    return ok


def schedule_hi(user_id: int, settings: Settings) -> None:
    """Fire-and-forget welcome ad (does not block the handler)."""
    if not _configured(settings):
        return
    _spawn(maybe_send_hi(user_id, settings), name=f"botohub-hi-{user_id}")


def schedule_ad(user_id: int, settings: Settings) -> None:
    """Fire-and-forget regular ad after an earn action."""
    if not _configured(settings):
        return
    _spawn(maybe_send_ad(user_id, settings), name=f"botohub-ad-{user_id}")


def _spawn(coro: Any, *, name: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run() -> None:
        try:
            await coro
        except Exception:
            log.warning("botohub_views_task_error", task=name, exc_info=True)

    loop.create_task(_run(), name=name)
