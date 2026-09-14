from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor
from app.op.http import as_dict, as_list, post_json
from app.op.manual import check_channels


class TGrassAdapter:
    """TGrass OP + optional channel list.

    If TGRASS_API_KEY is set, the adapter calls the configured TGrass HTTP API
    (default https://api.tgrass.online/v1 — override via TGRASS_API_URL).
    TGRASS_CHANNELS is an extra getChatMember list (same format as MANUAL_OP_CHANNELS).
    Missing credentials and empty channel list → skip. API errors → fail-open,
    then still try the local channel list if configured.
    """

    name = "tgrass"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._links: dict[int, list[str]] = {}

    def _channels(self) -> list[str]:
        return self._settings.parse_channel_list(self._settings.tgrass_channels)

    def _has_api(self) -> bool:
        return bool(self._settings.tgrass_api_key.strip())

    async def check(self, user: OpContext) -> OpResult:
        if not self._has_api() and not self._channels():
            return OpResult.skip(self.name, "TGrass API и каналы не заданы")

        api_result: OpResult | None = None
        if self._has_api():
            api_result = await self._check_api(user)
            if api_result.fail_open or api_result.skipped:
                api_result = None
            elif not api_result.allowed:
                return api_result

        if self._channels():
            remaining = await check_channels(user.bot, user.user_id, self._channels())
            if remaining:
                return OpResult.blocked(
                    self.name,
                    remaining,
                    "Подпишитесь на каналы TGrass.",
                )
        return api_result or OpResult.ok(self.name)

    async def verify(self, user: OpContext) -> OpResult:
        return await self.check(user)

    async def _check_api(self, user: OpContext) -> OpResult:
        try:
            status, payload = await post_json(
                f"{self._settings.tgrass_api_url.rstrip('/')}/check",
                json={
                    "user_id": user.user_id,
                    "chat_id": user.chat_id,
                    "language_code": user.language_code or "ru",
                },
                headers={
                    "Authorization": f"Bearer {self._settings.tgrass_api_key}",
                    "X-API-Key": self._settings.tgrass_api_key,
                    "Content-Type": "application/json",
                },
                timeout=self._settings.op_timeout_sec,
            )
            data = as_dict(payload)
            if status >= 500 or data.get("error"):
                return OpResult.fail_open_result(self.name, str(data.get("error") or status))
            if data.get("skip") is True or data.get("status") in {"ok", "skip", "passed"}:
                if not _pending(data):
                    return OpResult.ok(self.name)
            sponsors = [
                Sponsor(
                    title=str(item.get("name") or item.get("title") or "Спонсор TGrass"),
                    url=str(item.get("link") or item.get("url") or ""),
                    kind="channel",
                )
                for item in as_list(data)
                if isinstance(item, dict) and (item.get("link") or item.get("url"))
            ]
            if not sponsors:
                return OpResult.ok(self.name)
            return OpResult.blocked(self.name, sponsors)
        except Exception as exc:
            return OpResult.fail_open_result(self.name, str(exc))


def _pending(data: dict) -> bool:
    for item in as_list(data):
        if isinstance(item, dict) and str(item.get("status")) in {
            "unsubscribed",
            "pending",
            "incomplete",
        }:
            return True
    return False
