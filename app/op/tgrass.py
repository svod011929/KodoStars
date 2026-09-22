"""Tgrass OP adapter — https://tgrass.space/integration

* ``POST /offers`` (same endpoint for issue + verify)
* Header ``Auth: <api_key>`` (not Bearer)
* Response ``status``: ``ok`` / ``not_ok`` / ``no_offers``
* Offer ``subscribed`` bool; pending = not subscribed

Shown **before** device/twin checks (see ``PRE_DEVICE_CASCADE``).
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor, title_from_link
from app.op.http import as_dict, as_list, post_json


class TgrassAdapter:
    name = "tgrass"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _ready(self) -> bool:
        return bool(self._settings.tgrass_api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {
            "Auth": self._settings.tgrass_api_key.strip(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self) -> str:
        base = (self._settings.tgrass_api_url or "https://tgrass.space").rstrip("/")
        return f"{base}/offers"

    def _body(self, user: OpContext) -> dict[str, Any]:
        body: dict[str, Any] = {
            "tg_user_id": int(user.user_id),
            "is_premium": bool(user.is_premium),
            "lang": (user.language_code or "ru")[:8],
        }
        if user.username:
            body["tg_login"] = user.username
        limit = int(self._settings.tgrass_max_sponsors)
        if limit > 0:
            body["offers_limit"] = limit
        return body

    async def check(self, user: OpContext) -> OpResult:
        return await self._offers(user)

    async def verify(self, user: OpContext) -> OpResult:
        return await self._offers(user)

    async def _offers(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "TGRASS_API_KEY не задан")
        try:
            status, payload = await post_json(
                self._url(),
                json=self._body(user),
                headers=self._headers(),
                timeout_sec=self._settings.op_timeout_sec,
            )
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))

        data = as_dict(payload)
        if status >= 400:
            return OpResult.fail_open_result(self.name, str(data.get("detail") or data.get("message") or status))

        result_status = str(data.get("status") or "").lower()
        offers = as_list(data.get("offers") if isinstance(data.get("offers"), list) else data)
        if result_status in {"ok", "no_offers"}:
            return OpResult.ok(self.name, message=str(data.get("description") or result_status))
        if result_status == "not_ok":
            sponsors = _pending(offers)
            if not sponsors:
                return OpResult.ok(self.name)
            return OpResult.blocked(
                self.name,
                sponsors,
                "Выполните задания Tgrass и нажмите «Я подписался».",
            )
        # Unknown status — fail-open rather than lock users out.
        return OpResult.fail_open_result(self.name, f"unknown status={result_status or status}")


def _pending(items: list[Any]) -> list[Sponsor]:
    result: list[Sponsor] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        if bool(item.get("subscribed")):
            continue
        url = str(item.get("link") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        name = str(item.get("name") or "").strip()
        kind = str(item.get("type") or "channel").strip() or "channel"
        title = name or title_from_link(url, "Спонсор Tgrass")
        result.append(Sponsor(title=title, url=url, kind=kind))
    return result
