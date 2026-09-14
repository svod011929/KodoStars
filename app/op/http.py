from typing import Any

import aiohttp
import structlog

log = structlog.get_logger("kodostars.op.http")


async def post_json(
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> tuple[int, Any]:
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        async with session.post(url, json=json, headers=headers) as response:
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
