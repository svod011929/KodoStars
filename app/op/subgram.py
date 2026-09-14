from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor
from app.op.http import as_dict, as_list, post_json


class SubGramAdapter:
    """SubGram: POST /get-sponsors and POST /get-user-subscriptions (Auth header)."""

    name = "subgram"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._links: dict[int, list[str]] = {}

    def _ready(self) -> bool:
        return bool(self._settings.subgram_api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {
            "Auth": self._settings.subgram_api_key,
            "Content-Type": "application/json",
        }

    def _base(self) -> str:
        return self._settings.subgram_api_url.rstrip("/")

    async def check(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "SUBGRAM_API_KEY не задан")
        try:
            status, payload = await post_json(
                f"{self._base()}/get-sponsors",
                json={
                    "user_id": user.user_id,
                    "chat_id": user.chat_id,
                    "first_name": user.first_name,
                    "username": user.username,
                    "language_code": user.language_code or "ru",
                    "is_premium": user.is_premium,
                    "action": "subscribe",
                    "get_links": 1,
                    "max_sponsors": 8,
                },
                headers=self._headers(),
                timeout=self._settings.op_timeout_sec,
            )
            data = as_dict(payload)
            if status >= 500 or data.get("status") == "error":
                return OpResult.fail_open_result(
                    self.name, str(data.get("message") or status)
                )
            if data.get("status") in {"ok", "success"} and not _unsubscribed(data):
                return OpResult.ok(self.name)
            sponsors = _sponsors_from(data)
            self._links[user.user_id] = [item.url for item in sponsors]
            if not sponsors and data.get("status") != "warning":
                return OpResult.ok(self.name)
            return OpResult.blocked(
                self.name,
                sponsors,
                "Подпишитесь на спонсоров SubGram.",
            )
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))

    async def verify(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "SUBGRAM_API_KEY не задан")
        links = self._links.get(user.user_id, [])
        if not links:
            return await self.check(user)
        try:
            status, payload = await post_json(
                f"{self._base()}/get-user-subscriptions",
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
                Sponsor(
                    title=str(item.get("resource_name") or "Спонсор SubGram"),
                    url=str(item.get("link") or ""),
                    kind=str(item.get("type") or "channel"),
                )
                for item in as_list(data)
                if isinstance(item, dict)
                and str(item.get("status")) in {"unsubscribed", "notgetted", "not_counted"}
                and item.get("link")
            ]
            if remaining:
                return OpResult.blocked(self.name, remaining, "Ещё не все подписки засчитаны.")
            return OpResult.ok(self.name)
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))


def _unsubscribed(data: dict) -> bool:
    for item in as_list(data):
        if isinstance(item, dict) and str(item.get("status")) in {
            "unsubscribed",
            "notgetted",
            "not_counted",
        }:
            return True
    return False


def _sponsors_from(data: dict) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for item in as_list(data):
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or item.get("url") or "")
        if not url:
            continue
        if str(item.get("status")) == "subscribed":
            continue
        sponsors.append(
            Sponsor(
                title=str(item.get("resource_name") or item.get("name") or "Спонсор SubGram"),
                url=url,
                kind=str(item.get("type") or "channel"),
            )
        )
    return sponsors
