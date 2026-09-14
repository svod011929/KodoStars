from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor
from app.op.http import as_dict, as_list, post_json


class PiarFlowAdapter:
    """PiarFlow: POST https://piarflow.com/v1/sponsors and /sponsors/check (Bearer)."""

    name = "piarflow"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._links: dict[int, list[str]] = {}

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
        try:
            status, payload = await post_json(
                f"{self._base()}/sponsors",
                json={
                    "user_id": user.user_id,
                    "chat_id": user.chat_id,
                    "max_sponsors": self._settings.piarflow_max_sponsors,
                    "first_name": user.first_name,
                    "username": user.username,
                    "language_code": user.language_code or "ru",
                },
                headers=self._headers(),
                timeout=self._settings.op_timeout_sec,
            )
            data = as_dict(payload)
            if status >= 500 or data.get("status") == "error":
                return OpResult.fail_open_result(
                    self.name, str(data.get("message") or status)
                )
            sponsors = [
                Sponsor(title="Спонсор PiarFlow", url=str(item.get("link")), kind="channel")
                for item in as_list(data)
                if isinstance(item, dict)
                and item.get("link")
                and str(item.get("status")) != "subscribed"
            ]
            self._links[user.user_id] = [item.url for item in sponsors]
            if not sponsors:
                return OpResult.ok(self.name)
            return OpResult.blocked(self.name, sponsors, "Подпишитесь на спонсоров PiarFlow.")
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))

    async def verify(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "PIARFLOW_API_KEY не задан")
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
            if status >= 500 or data.get("status") == "error":
                return OpResult.fail_open_result(
                    self.name, str(data.get("message") or status)
                )
            remaining = [
                Sponsor(title="Спонсор PiarFlow", url=str(item.get("link")), kind="channel")
                for item in as_list(data)
                if isinstance(item, dict)
                and item.get("link")
                and str(item.get("status")) == "unsubscribed"
            ]
            if remaining:
                return OpResult.blocked(self.name, remaining)
            return OpResult.ok(self.name)
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))
