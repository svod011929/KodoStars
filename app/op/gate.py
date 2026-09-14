from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.op.base import OpAdapter, OpResult
from app.op.botohub import BotoHubAdapter
from app.op.flyer import FlyerAdapter
from app.op.manual import ManualOpAdapter
from app.op.piarflow import PiarFlowAdapter
from app.op.subgram import SubGramAdapter
from app.op.tgrass import TGrassAdapter


class OpGate:
    def __init__(self, settings: Settings, adapters: Sequence[OpAdapter] | None = None) -> None:
        self.settings = settings
        self.adapters = list(adapters or default_adapters(settings))

    async def check(self, session: AsyncSession, user: User) -> OpResult:
        del session
        if not self.settings.op_enabled:
            return OpResult(True, "disabled", reason="op_disabled")
        for adapter in self.adapters:
            result = await adapter.check(user)
            if result.passed and result.reason in {"skipped_no_key", "skipped_no_links"}:
                continue
            if not result.passed:
                return result
        return OpResult(True, "cascade", reason="all_passed")

    async def verify(self, session: AsyncSession, user: User) -> OpResult:
        del session
        if not self.settings.op_enabled:
            return OpResult(True, "disabled", reason="op_disabled")
        for adapter in self.adapters:
            result = await adapter.verify(user)
            if result.passed and result.reason in {"skipped_no_key", "skipped_no_links"}:
                continue
            if not result.passed:
                return result
        return OpResult(True, "cascade", reason="all_passed")


def default_adapters(settings: Settings) -> list[OpAdapter]:
    return [
        FlyerAdapter(settings),
        SubGramAdapter(settings),
        BotoHubAdapter(settings),
        PiarFlowAdapter(settings),
        TGrassAdapter(settings),
        ManualOpAdapter(settings),
    ]
