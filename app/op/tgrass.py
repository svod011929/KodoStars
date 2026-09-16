"""TGrass OP adapter — https://tgrass.space/integration

``POST https://tgrass.space/offers`` with header ``Auth: <api key>`` returns the
user's offers *and* checks them in one call::

    {"status": "ok" | "not_ok" | "no_offers",
     "offers": [{"name", "link", "subscribed", "type", "channel_id", "offer_id"}],
     "description": "..."}

Required body fields: ``tg_user_id``, ``is_premium``, ``lang``; optional
``tg_login``, ``offers_limit``. «Я подписался» repeats the same request.

``TGRASS_CHANNELS`` is a local extra: a plain ``getChatMember`` list checked after
the API (same format as ``MANUAL_OP_CHANNELS``). Missing key and empty channel list
→ skip; API errors → fail-open (the local list is still checked).
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor, title_from_link
from app.op.http import as_dict, post_json
from app.op.manual import check_channels

OFFER_TITLES = {
    "bot": "Запустить бота",
    "channel": "Подписаться на канал",
    "resource": "Перейти по ссылке",
    "folder": "Добавить папку",
}


class TGrassAdapter:
    name = "tgrass"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _channels(self) -> list[str]:
        return self._settings.parse_channel_list(self._settings.tgrass_channels)

    def _has_api(self) -> bool:
        return bool(self._settings.tgrass_api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {"Auth": self._settings.tgrass_api_key, "Content-Type": "application/json"}

    def _url(self) -> str:
        return f"{self._settings.tgrass_api_url.rstrip('/')}/offers"

    async def check(self, user: OpContext) -> OpResult:
        if not self._has_api() and not self._channels():
            return OpResult.skip(self.name, "TGrass API и каналы не заданы")

        api_result: OpResult | None = None
        if self._has_api():
            api_result = await self._check_api(user)
            if not api_result.allowed:
                return api_result

        if self._channels():
            remaining = await check_channels(user.bot, user.user_id, self._channels())
            if remaining:
                return OpResult.blocked(self.name, remaining, "Подпишитесь на каналы TGrass.")
            return OpResult.ok(self.name)
        # Keep the fail-open flag visible in logs when the API was the only source.
        return api_result or OpResult.ok(self.name)

    async def verify(self, user: OpContext) -> OpResult:
        return await self.check(user)

    async def _check_api(self, user: OpContext) -> OpResult:
        body: dict[str, Any] = {
            "tg_user_id": user.user_id,
            "is_premium": bool(user.is_premium),
            "lang": user.language_code or "ru",
        }
        if user.username:
            body["tg_login"] = user.username
        if self._settings.tgrass_offers_limit > 0:
            body["offers_limit"] = self._settings.tgrass_offers_limit
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
        if status >= 400 or data.get("detail") or data.get("error"):
            return OpResult.fail_open_result(
                self.name, str(data.get("detail") or data.get("error") or status)
            )
        state = str(data.get("status") or "").lower()
        if state in {"ok", "no_offers"}:
            return OpResult.ok(self.name)
        if state != "not_ok":
            return OpResult.fail_open_result(self.name, f"unexpected status {state!r}")
        pending = _pending_offers(data.get("offers"))
        if not pending:
            return OpResult.ok(self.name)
        return OpResult.blocked(self.name, pending, "Выполните задания и нажмите «Я подписался».")


def _pending_offers(offers: Any) -> list[Sponsor]:
    if not isinstance(offers, list):
        return []
    result: list[Sponsor] = []
    for item in offers:
        if not isinstance(item, dict) or item.get("subscribed") is True:
            continue
        url = str(item.get("link") or "")
        if not url:
            continue
        kind = str(item.get("type") or "channel")
        title = str(item.get("name") or "").strip() or title_from_link(
            url, OFFER_TITLES.get(kind, "Спонсор TGrass")
        )
        result.append(Sponsor(title=title, url=url, kind=kind))
    return result
