"""BotoHub OP adapter — https://botohub.me/integration

``POST https://botohub.me/get-tasks-extended`` with header ``Auth: <token>`` and body
``{"chat_id": <telegram user id>, "max_op": N}`` returns::

    {"tasks": [{"url": ..., "resource_id": ..., "completed": bool}, ...],
     "completed": bool, "skip": bool}

Sponsors are pinned to the user for ~3 minutes, so «Я подписался» simply repeats
the same request and reads the fresh ``completed`` flags. ``skip`` means BotoHub has
nothing to show; a blocked bot or an invalid request yields ``{"tasks": []}``.
Errors (401 ``{"error": "Unauthorized"}``, 400, 5xx, transport) → fail-open.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor, title_from_link
from app.op.http import as_dict, post_json


class BotoHubAdapter:
    name = "botohub"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _ready(self) -> bool:
        return bool(self._settings.botohub_api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {"Auth": self._settings.botohub_api_key, "Content-Type": "application/json"}

    def _url(self) -> str:
        return f"{self._settings.botohub_api_url.rstrip('/')}/get-tasks-extended"

    async def check(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "BOTOHUB_API_KEY не задан")
        body: dict[str, Any] = {"chat_id": user.user_id}
        if self._settings.botohub_max_op > 0:
            body["max_op"] = self._settings.botohub_max_op
        try:
            status, payload = await post_json(
                self._url(),
                json=body,
                headers=self._headers(),
                timeout_sec=self._settings.op_timeout_sec,
            )
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))
        data = as_dict(payload)
        if status >= 400 or data.get("error"):
            return OpResult.fail_open_result(self.name, str(data.get("error") or status))
        if data.get("skip") is True or data.get("completed") is True:
            return OpResult.ok(self.name)
        pending = _pending_sponsors(data.get("tasks"))
        if not pending:
            return OpResult.ok(self.name)
        return OpResult.blocked(self.name, pending, "Подпишитесь на спонсоров и нажмите «Я подписался».")

    async def verify(self, user: OpContext) -> OpResult:
        return await self.check(user)


def _pending_sponsors(tasks: Any) -> list[Sponsor]:
    if not isinstance(tasks, list):
        return []
    result: list[Sponsor] = []
    for item in tasks:
        if isinstance(item, str):
            # Plain /get-tasks format: bare links, completed ones are already removed.
            url = item
        elif isinstance(item, dict):
            if item.get("completed") is True:
                continue
            url = str(item.get("url") or item.get("link") or "")
        else:
            continue
        if not url:
            continue
        kind = "bot" if "?start" in url or url.rstrip("/").lower().endswith("bot") else "channel"
        result.append(Sponsor(title=title_from_link(url, "Спонсор BotoHub"), url=url, kind=kind))
    return result
