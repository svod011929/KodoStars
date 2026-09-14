from __future__ import annotations

from app.config import Settings
from app.db.models import User
from app.op.base import OpAdapter, OpResult
from app.op.http import OpHttpError, op_request


class TGrassAdapter(OpAdapter):
    name = "tgrass"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self, user: User) -> OpResult:
        if not self.settings.tgrass_api_key:
            return OpResult(True, self.name, reason="skipped_no_key")
        try:
            payload = await op_request(
                method="GET",
                url=f"{self.settings.tgrass_base_url.rstrip('/')}/subscription/check",
                provider=self.name,
                headers={"Authorization": f"Bearer {self.settings.tgrass_api_key}"},
                params={"tg_id": user.telegram_id},
            )
        except OpHttpError as exc:
            return OpResult(True, self.name, reason="fail_open", extra={"error": str(exc)})

        data = payload if isinstance(payload, dict) else {}
        if data.get("subscribed") or data.get("ok"):
            return OpResult(True, self.name, extra=data)
        links = [str(item) for item in data.get("required", []) if item]
        return OpResult(False, self.name, reason="not_subscribed", links=links, extra=data)
