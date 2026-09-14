from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor
from app.op.http import as_dict, as_list, post_json


class FlyerAdapter:
    """Flyer OP: POST https://api.flyerservice.io/check (+ get_tasks)."""

    name = "flyer"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _ready(self) -> bool:
        return bool(self._settings.flyer_api_key.strip())

    async def check(self, user: OpContext) -> OpResult:
        if not self._ready():
            return OpResult.skip(self.name, "FLYER_API_KEY не задан")
        try:
            status, payload = await post_json(
                f"{self._settings.flyer_api_url.rstrip('/')}/check",
                json={
                    "key": self._settings.flyer_api_key,
                    "user_id": user.user_id,
                    "language_code": user.language_code or "ru",
                },
                timeout=self._settings.op_timeout_sec,
            )
            data = as_dict(payload)
            if status >= 500 or data.get("error"):
                return OpResult.fail_open_result(self.name, str(data.get("error") or status))
            if data.get("skip", False) is True:
                return OpResult.ok(self.name)
            sponsors = await self._tasks(user)
            if not sponsors:
                # Flyer often delivers the OP message itself when skip=false.
                return OpResult.blocked(
                    self.name,
                    [],
                    "Подпишитесь на спонсоров Flyer и нажмите «Я подписался».",
                )
            return OpResult.blocked(self.name, sponsors)
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))

    async def verify(self, user: OpContext) -> OpResult:
        return await self.check(user)

    async def _tasks(self, user: OpContext) -> list[Sponsor]:
        try:
            status, payload = await post_json(
                f"{self._settings.flyer_api_url.rstrip('/')}/get_tasks",
                json={
                    "key": self._settings.flyer_api_key,
                    "user_id": user.user_id,
                    "language_code": user.language_code or "ru",
                    "limit": 8,
                },
                timeout=self._settings.op_timeout_sec,
            )
            if status >= 400:
                return []
            incomplete = {"incomplete", "waiting", "pending", "assigned", "0", 0, False}
            sponsors: list[Sponsor] = []
            for item in as_list(payload if isinstance(payload, list) else as_dict(payload)):
                if not isinstance(item, dict):
                    continue
                if item.get("status") not in incomplete and item.get("status") not in (
                    None,
                    "",
                ):
                    if str(item.get("status")).lower() in {
                        "complete",
                        "completed",
                        "done",
                        "ok",
                    }:
                        continue
                url = str(item.get("link") or item.get("url") or "")
                if not url:
                    continue
                sponsors.append(
                    Sponsor(
                        title=str(item.get("name") or item.get("title") or "Спонсор Flyer"),
                        url=url,
                        kind=str(item.get("type") or "channel"),
                    )
                )
            return sponsors
        except Exception:
            return []
