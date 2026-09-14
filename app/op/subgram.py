from __future__ import annotations

from app.config import Settings
from app.db.models import User
from app.op.base import OpAdapter, OpResult
from app.op.http import OpHttpError, op_request


class SubGramAdapter(OpAdapter):
    name = "subgram"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self, user: User) -> OpResult:
        if not self.settings.subgram_api_key:
            return OpResult(True, self.name, reason="skipped_no_key")
        try:
            payload = await op_request(
                method="POST",
                url=f"{self.settings.subgram_base_url.rstrip('/')}/request-op",
                provider=self.name,
                headers={"Authorization": self.settings.subgram_api_key},
                json={
                    "user_id": user.telegram_id,
                    "chat_id": user.telegram_id,
                },
            )
        except OpHttpError as exc:
            return OpResult(True, self.name, reason="fail_open", extra={"error": str(exc)})

        data = payload if isinstance(payload, dict) else {}
        status = str(data.get("status") or data.get("code") or "").lower()
        links = [str(item) for item in data.get("sponsors", data.get("links", [])) if item]
        if status in {"ok", "passed", "skip"}:
            return OpResult(True, self.name, extra=data)
        return OpResult(False, self.name, reason=status or "not_subscribed", links=links, extra=data)
