"""Trafsly OP adapter — https://trafsly.com/api-docs

* ``POST /api/v1/get-sponsors`` (header ``Auth: at_…``) with ``user_id`` and
  targeting fields (``first_name``, ``username``, ``language_code``,
  ``is_premium``, ``max_sponsors``, ``action``). ``status: "ok"`` → the user may
  proceed; ``status: "warning"`` → show ``sponsors[] = {ads_id, link,
  resource_type, title, status}``.
* ``POST /api/v1/confirm-subscription`` with ``user_id`` and one ``ads_id`` — called
  for every issued sponsor when the user presses «Я подписался». Trafsly verifies
  through ``getChatMember`` and answers ``subscribed: true/false`` with HTTP 200
  even on refusal (see ``message``).

Only ``ads_id`` values issued to *this* user by ``get-sponsors`` are confirmed
(they expire after an hour — ``Sponsor was not shown`` / ``Order not found`` make
us re-fetch). ``User is banned`` → pass (nothing to show). 401/422/429/5xx and
transport errors → fail-open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.op.base import BoundedCache, OpContext, OpResult, Sponsor, title_from_link
from app.op.http import as_dict, post_json

PENDING_STATUSES = frozenset({"unsubscribed"})
REFETCH_MESSAGES = ("order not found", "sponsor was not shown")


@dataclass(slots=True)
class _Issued:
    ads_id: int
    sponsor: Sponsor


class TrafslyAdapter:
    name = "trafsly"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._issued: BoundedCache[int, list[_Issued]] = BoundedCache()

    def _ready(self) -> bool:
        return bool(self._settings.trafsly_api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {"Auth": self._settings.trafsly_api_key, "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self._settings.trafsly_api_url.rstrip('/')}/api/v1/{path.lstrip('/')}"

    async def _post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        status, payload = await post_json(
            self._url(path),
            json=body,
            headers=self._headers(),
            timeout_sec=self._settings.op_timeout_sec,
        )
        return status, as_dict(payload)

    async def check(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "TRAFSLY_API_KEY не задан")
        body: dict[str, Any] = {
            "user_id": user.user_id,
            "chat_id": user.chat_id,
            "is_premium": bool(user.is_premium),
            "max_sponsors": self._settings.trafsly_max_sponsors,
            "action": "subscribe",
        }
        # Targeting fields: unknown values are omitted (unknown = pass on Trafsly's side).
        if user.language_code:
            body["language_code"] = user.language_code
        if user.first_name:
            body["first_name"] = user.first_name
        if user.username:
            body["username"] = user.username
        try:
            status, data = await self._post("get-sponsors", body)
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))
        if status >= 400 or data.get("detail"):
            return OpResult.fail_open_result(self.name, str(data.get("detail") or status))
        issued = _issued_from(data.get("sponsors"))
        self._issued.set(user.user_id, issued)
        if str(data.get("status") or "").lower() == "ok" or not issued:
            return OpResult.ok(self.name)
        return OpResult.blocked(
            self.name,
            [entry.sponsor for entry in issued],
            "Подпишитесь на спонсоров и нажмите «Я подписался».",
        )

    async def verify(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "TRAFSLY_API_KEY не задан")
        issued = self._issued.get(user.user_id) or []
        if not issued:
            return await self.check(user)
        remaining: list[_Issued] = []
        for entry in issued:
            try:
                status, data = await self._post(
                    "confirm-subscription", {"user_id": user.user_id, "ads_id": entry.ads_id}
                )
            except Exception as exc:
                return OpResult.fail_open_result(self.name, str(exc))
            if status >= 400 or data.get("detail"):
                return OpResult.fail_open_result(self.name, str(data.get("detail") or status))
            if data.get("subscribed") is True:
                continue
            message = str(data.get("message") or "").lower()
            if message == "user is banned":
                self._issued.pop(user.user_id)
                return OpResult.ok(self.name)
            if any(marker in message for marker in REFETCH_MESSAGES):
                # The issued list is stale: ask for a fresh one.
                self._issued.pop(user.user_id)
                return await self.check(user)
            remaining.append(entry)
        if remaining:
            self._issued.set(user.user_id, remaining)
            return OpResult.blocked(
                self.name,
                [entry.sponsor for entry in remaining],
                "Ещё не все подписки подтверждены.",
            )
        self._issued.pop(user.user_id)
        return OpResult.ok(self.name)


def _issued_from(items: Any) -> list[_Issued]:
    if not isinstance(items, list):
        return []
    result: list[_Issued] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "unsubscribed").lower() not in PENDING_STATUSES:
            continue
        url = str(item.get("link") or "")
        ads_id = item.get("ads_id")
        if not url or not isinstance(ads_id, int):
            continue
        kind = str(item.get("resource_type") or "channel")
        title = str(item.get("title") or "").strip() or title_from_link(url, "Спонсор Trafsly")
        result.append(_Issued(ads_id=ads_id, sponsor=Sponsor(title=title, url=url, kind=kind)))
    return result
