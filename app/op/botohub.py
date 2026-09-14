from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor
from app.op.http import as_dict, as_list, post_json


class BotoHubAdapter:
    """BotoHub (botohub.me) OP adapter.

    Public site does not publish a frozen OpenAPI dump. The adapter follows the
    same exchange pattern as other OP hubs: POST /sponsors then POST /sponsors/check
    with an API key. Override BOTOHUB_API_URL if your cabinet shows a different base.
    Missing key → skip. HTTP/5xx/parse errors → fail-open.
    """

    name = "botohub"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._links: dict[int, list[str]] = {}

    def _ready(self) -> bool:
        return bool(self._settings.botohub_api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.botohub_api_key}",
            "X-API-Key": self._settings.botohub_api_key,
            "Content-Type": "application/json",
        }

    def _base(self) -> str:
        return self._settings.botohub_api_url.rstrip("/")

    async def check(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "BOTOHUB_API_KEY не задан")
        body: dict = {
            "user_id": user.user_id,
            "chat_id": user.chat_id,
            "first_name": user.first_name,
            "username": user.username,
            "language_code": user.language_code or "ru",
        }
        if self._settings.botohub_bot_id:
            body["bot_id"] = self._settings.botohub_bot_id
        try:
            status, payload = await post_json(
                f"{self._base()}/sponsors",
                json=body,
                headers=self._headers(),
                timeout=self._settings.op_timeout_sec,
            )
            data = as_dict(payload)
            if status >= 500 or str(data.get("status", "")).lower() in {"error", "fail"}:
                return OpResult.fail_open_result(
                    self.name, str(data.get("message") or status)
                )
            sponsors = _sponsors(data)
            self._links[user.user_id] = [item.url for item in sponsors]
            if not sponsors:
                return OpResult.ok(self.name)
            return OpResult.blocked(self.name, sponsors, "Подпишитесь на спонсоров BotoHub.")
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))

    async def verify(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "BOTOHUB_API_KEY не задан")
        links = self._links.get(user.user_id, [])
        if not links:
            return await self.check(user)
        try:
            status, payload = await post_json(
                f"{self._base()}/sponsors/check",
                json={"user_id": user.user_id, "links": links},
                headers=self._headers(),
                timeout=self._settings.op_timeout_sec,
            )
            data = as_dict(payload)
            if status >= 500:
                return OpResult.fail_open_result(self.name, str(status))
            remaining = [
                Sponsor(
                    title=str(item.get("name") or item.get("title") or "Спонсор BotoHub"),
                    url=str(item.get("link") or item.get("url") or ""),
                    kind=str(item.get("type") or "channel"),
                )
                for item in as_list(data)
                if isinstance(item, dict)
                and str(item.get("status")) not in {"subscribed", "ok", "completed"}
                and (item.get("link") or item.get("url"))
            ]
            if remaining:
                return OpResult.blocked(self.name, remaining)
            return OpResult.ok(self.name)
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))


def _sponsors(data: dict) -> list[Sponsor]:
    result: list[Sponsor] = []
    for item in as_list(data):
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or item.get("url") or "")
        if not url or str(item.get("status")) == "subscribed":
            continue
        result.append(
            Sponsor(
                title=str(item.get("name") or item.get("title") or "Спонсор BotoHub"),
                url=url,
                kind=str(item.get("type") or "channel"),
            )
        )
    return result
