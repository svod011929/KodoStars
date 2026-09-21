"""PiarFlow OP adapter — https://piarflow.com/api-docs

* ``POST /sponsors`` / ``POST /sponsors/check``
* Statuses: ``subscribed`` — done and paid by PiarFlow; ``not_counted`` — done but
  unpaid; ``unsubscribed`` — pending.

Paid (``subscribed``) links are returned on ``OpResult.paid_links`` so the bot can
gate referral bonuses on real monetized traffic quality.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.op.base import BoundedCache, OpContext, OpResult, Sponsor, title_from_link
from app.op.http import as_dict, as_list, post_json

DONE_STATUSES = frozenset({"subscribed", "not_counted"})
PAID_STATUS = "subscribed"


class PiarFlowAdapter:
    name = "piarflow"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._links: BoundedCache[int, list[str]] = BoundedCache()

    def _ready(self) -> bool:
        return bool(self._settings.piarflow_api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.piarflow_api_key}",
            "Content-Type": "application/json",
        }

    def _base(self) -> str:
        return self._settings.piarflow_api_url.rstrip("/")

    async def check(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "PIARFLOW_API_KEY не задан")
        body: dict[str, Any] = {
            "user_id": user.user_id,
            "chat_id": user.chat_id,
            "max_sponsors": self._settings.piarflow_max_sponsors,
            "first_name": user.first_name or None,
            "username": user.username or None,
            "language_code": user.language_code or None,
            "bio": None,
        }
        try:
            status, payload = await post_json(
                f"{self._base()}/sponsors",
                json=body,
                headers=self._headers(),
                timeout_sec=self._settings.op_timeout_sec,
            )
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))
        if status == 404:
            return OpResult.ok(self.name)
        data = as_dict(payload)
        if status >= 400 or data.get("status") == "error":
            return OpResult.fail_open_result(self.name, str(data.get("message") or status))
        items = as_list(data)
        paid = _paid_links(items)
        sponsors = _pending(items)
        self._links.set(user.user_id, [item.url for item in sponsors])
        if not sponsors:
            return OpResult.ok(self.name, paid_links=paid)
        return OpResult.blocked(
            self.name,
            sponsors,
            "Выполните задания PiarFlow и нажмите «Я подписался».",
            paid_links=paid,
        )

    async def verify(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "PIARFLOW_API_KEY не задан")
        links = self._links.get(user.user_id) or []
        if not links:
            return await self.check(user)
        try:
            status, payload = await post_json(
                f"{self._base()}/sponsors/check",
                json={"user_id": user.user_id, "links": links},
                headers=self._headers(),
                timeout_sec=self._settings.op_timeout_sec,
            )
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))
        if status == 404:
            self._links.pop(user.user_id)
            return OpResult.ok(self.name)
        data = as_dict(payload)
        if status >= 400 or data.get("status") == "error":
            return OpResult.fail_open_result(self.name, str(data.get("message") or status))
        items = as_list(data)
        paid = _paid_links(items)
        remaining = _pending(items)
        if remaining:
            return OpResult.blocked(
                self.name, remaining, "Ещё не все задания выполнены.", paid_links=paid
            )
        self._links.pop(user.user_id)
        return OpResult.ok(self.name, paid_links=paid)


def _paid_links(items: list[Any]) -> list[str]:
    """Links where PiarFlow credited the traffic sale (``subscribed``)."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or "").strip()
        if not url or url in seen:
            continue
        if str(item.get("status") or "").lower() != PAID_STATUS:
            continue
        seen.add(url)
        result.append(url)
    return result


def _pending(items: list[Any]) -> list[Sponsor]:
    result: list[Sponsor] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or "")
        if not url or str(item.get("status") or "").lower() in DONE_STATUSES:
            continue
        result.append(Sponsor(title=title_from_link(url, "Спонсор PiarFlow"), url=url, kind="channel"))
    return result
