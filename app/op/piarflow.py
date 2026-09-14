from __future__ import annotations

from app.config import Settings
from app.db.models import User
from app.op.base import OpAdapter, OpResult
from app.op.http import OpHttpError, op_request


class PiarFlowAdapter(OpAdapter):
    name = "piarflow"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self, user: User) -> OpResult:
        if not self.settings.piarflow_api_key:
            return OpResult(True, self.name, reason="skipped_no_key")
        try:
            payload = await op_request(
                method="POST",
                url=f"{self.settings.piarflow_base_url.rstrip('/')}/check",
                provider=self.name,
                headers={"X-Token": self.settings.piarflow_api_key},
                json={"telegram_id": user.telegram_id},
            )
        except OpHttpError as exc:
            return OpResult(True, self.name, reason="fail_open", extra={"error": str(exc)})

        data = payload if isinstance(payload, dict) else {}
        if data.get("passed") or data.get("ok"):
            return OpResult(True, self.name, extra=data)
        links = [str(item) for item in data.get("links", []) if item]
        return OpResult(False, self.name, reason="not_subscribed", links=links, extra=data)
