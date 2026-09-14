from __future__ import annotations

from app.config import Settings
from app.db.models import User
from app.op.base import OpAdapter, OpResult


class ManualOpAdapter(OpAdapter):
    name = "manual"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self, user: User) -> OpResult:
        links = [link.strip() for link in self.settings.manual_op_links if link.strip()]
        if not links:
            return OpResult(True, self.name, reason="skipped_no_links")
        extra = {"checked_user": user.telegram_id}
        return OpResult(False, self.name, reason="manual_required", links=links, extra=extra)
