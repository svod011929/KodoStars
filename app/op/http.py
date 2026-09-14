from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)


class OpHttpError(Exception):
    def __init__(self, provider: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


async def op_request(
    *,
    method: str,
    url: str,
    provider: str,
    timeout: float = 12.0,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any] | str:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                json=json,
                data=data,
                params=params,
            )
    except httpx.HTTPError as exc:
        log.warning("op_http_error", provider=provider, url=url, error=str(exc))
        raise OpHttpError(provider, str(exc)) from exc

    if response.status_code >= 400:
        log.warning(
            "op_http_status",
            provider=provider,
            url=url,
            status=response.status_code,
            body=response.text[:400],
        )
        raise OpHttpError(provider, response.text[:400], status_code=response.status_code)

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = response.json()
        if isinstance(payload, (dict, list)):
            return payload
        return {"value": payload}
    return response.text
