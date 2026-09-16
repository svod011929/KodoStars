"""Shared aiohttp client for OP providers (one connection pool per process)."""

from typing import Any

import aiohttp
import structlog

log = structlog.get_logger("kodostars.op.http")

_session: aiohttp.ClientSession | None = None


def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            headers={"User-Agent": "KodoStars/1.0 (+https://github.com/svod011929/KodoStars)"},
        )
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def post_json(
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_sec: float = 8.0,
) -> tuple[int, Any]:
    timeout_cfg = aiohttp.ClientTimeout(total=timeout_sec)
    session = get_session()
    async with session.post(url, json=json, headers=headers, timeout=timeout_cfg) as response:
        try:
            payload = await response.json(content_type=None)
        except Exception:
            payload = await response.text()
        return response.status, payload


def as_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def as_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("sponsors", "tasks", "items", "result", "additional"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict) and "sponsors" in value:
                inner = value.get("sponsors")
                if isinstance(inner, list):
                    return inner
    return []
