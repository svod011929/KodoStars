from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ProviderState
from app.op.base import OpAdapter, OpContext, OpResult
from app.op.botohub import BotoHubAdapter
from app.op.flyer import FlyerAdapter
from app.op.manual import ManualAdapter
from app.op.piarflow import PiarFlowAdapter
from app.op.subgram import SubGramAdapter
from app.op.tgrass import TGrassAdapter

log = structlog.get_logger("kodostars.op")

CASCADE: tuple[str, ...] = (
    "flyer",
    "subgram",
    "botohub",
    "piarflow",
    "tgrass",
    "manual",
)


class OpGate:
    def __init__(self, settings: Settings, adapters: Sequence[OpAdapter] | None = None) -> None:
        self._settings = settings
        self._adapters = list(adapters) if adapters is not None else default_adapters(settings)
        self._by_name = {adapter.name: adapter for adapter in self._adapters}

    async def enforce(
        self,
        ctx: OpContext,
        session: AsyncSession,
        *,
        verify: bool = False,
    ) -> OpResult:
        enabled = await enabled_providers(session, self._settings)
        for name in CASCADE:
            if name not in enabled:
                log.info("op_provider_disabled", provider=name)
                continue
            adapter = self._by_name.get(name)
            if adapter is None:
                continue
            result = await (adapter.verify(ctx) if verify else adapter.check(ctx))
            log.info(
                "op_provider_result",
                provider=name,
                allowed=result.allowed,
                skipped=result.skipped,
                fail_open=result.fail_open,
                sponsors=len(result.sponsors),
            )
            if result.skipped or result.fail_open:
                continue
            if not result.allowed:
                return result
        return OpResult.ok("gate")


def default_adapters(settings: Settings) -> list[OpAdapter]:
    return [
        FlyerAdapter(settings),
        SubGramAdapter(settings),
        BotoHubAdapter(settings),
        PiarFlowAdapter(settings),
        TGrassAdapter(settings),
        ManualAdapter(settings),
    ]


async def enabled_providers(session: AsyncSession, settings: Settings) -> set[str]:
    defaults = {
        "flyer": settings.flyer_enabled,
        "subgram": settings.subgram_enabled,
        "botohub": settings.botohub_enabled,
        "piarflow": settings.piarflow_enabled,
        "tgrass": settings.tgrass_enabled,
        "manual": settings.manual_enabled,
    }
    result = await session.execute(select(ProviderState))
    rows = {row.name: row.enabled for row in result.scalars().all()}
    enabled = set()
    for name, default in defaults.items():
        flag = rows.get(name, default)
        if flag:
            enabled.add(name)
    return enabled


async def toggle_provider(
    session: AsyncSession,
    name: str,
    *,
    admin_id: int,
) -> ProviderState | None:
    if name not in CASCADE:
        return None
    row = await session.get(ProviderState, name)
    if row is None:
        row = ProviderState(name=name, enabled=True)
        session.add(row)
        await session.flush()
    row.enabled = not row.enabled
    row.updated_by = admin_id
    await session.flush()
    return row
