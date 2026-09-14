from __future__ import annotations

from app.config import Settings
from app.db.models import User
from app.op.base import OpAdapter, OpResult
from app.op.http import OpHttpError, op_request


class BotoHubAdapter(OpAdapter):
    name = "botohub"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self, user: User) -> OpResult:
        if not self.settings.botohub_api_key:
            return OpResult(True, self.name, reason="skipped_no_key")
        try:
            payload = await op_request(
                method="GET",
                url=f"{self.settings.botohub_base_url.rstrip('/')}/op/check",
                provider=self.name,
                headers={"X-Api-Key": self.settings.botohub_api_key},
                params={"user_id": user.telegram_id},
            )
        except OpHttpError as exc:
            return OpResult(True, self.name, reason="fail_open", extra={"error": str(exc)})

        data = payload if isinstance(payload, dict) else {}
        passed = bool(data.get("ok") or data.get("passed"))
        links = [str(item) for item in data.get("channels", []) if item]
        if passed:
            return OpResult(True, self.name, extra=data)
        return OpResult(False, self.name, reason="not_subscribed", links=links, extra=data)
