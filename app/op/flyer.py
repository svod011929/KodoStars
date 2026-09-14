from __future__ import annotations

from app.config import Settings
from app.db.models import User
from app.op.base import OpAdapter, OpResult
from app.op.http import OpHttpError, op_request


class FlyerAdapter(OpAdapter):
    name = "flyer"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self, user: User) -> OpResult:
        if not self.settings.flyer_api_key:
            return OpResult(True, self.name, reason="skipped_no_key")
        try:
            payload = await op_request(
                method="POST",
                url=f"{self.settings.flyer_base_url.rstrip('/')}/check",
                provider=self.name,
                headers={"Authorization": f"Bearer {self.settings.flyer_api_key}"},
                json={
                    "user_id": user.telegram_id,
                    "language": user.language_code or "ru",
                },
            )
        except OpHttpError as exc:
            return OpResult(True, self.name, reason="fail_open", extra={"error": str(exc)})

        data = payload if isinstance(payload, dict) else {}
        status = str(data.get("status") or data.get("result") or "").lower()
        links = [str(item) for item in data.get("links", []) if item]
        if status in {"ok", "passed", "skip", "skipped"}:
            return OpResult(True, self.name, extra=data)
        return OpResult(False, self.name, reason=status or "not_subscribed", links=links, extra=data)
