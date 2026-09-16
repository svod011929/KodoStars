from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ProviderState
from app.db.txn import commit_before_io
from app.op.base import OpAdapter, OpContext, OpResult
from app.op.botohub import BotoHubAdapter
from app.op.flyer import FlyerAdapter
from app.op.manual import ManualAdapter
from app.op.piarflow import PiarFlowAdapter
from app.op.subgram import SubGramAdapter
from app.op.tgrass import TGrassAdapter
from app.op.trafsly import TrafslyAdapter

log = structlog.get_logger("kodostars.op")

CASCADE: tuple[str, ...] = (
    "flyer",
    "subgram",
    "botohub",
    "piarflow",
    "tgrass",
    "trafsly",
    "manual",
)

PROVIDER_TITLES: dict[str, str] = {
    "flyer": "Flyer",
    "subgram": "SubGram",
    "botohub": "BotoHub",
    "piarflow": "PiarFlow",
    "tgrass": "TGrass",
    "trafsly": "Trafsly",
    "manual": "Свои каналы",
}

PROVIDER_DOCS: dict[str, str] = {
    "flyer": "https://api.flyerhubs.com/",
    "subgram": "https://subgram.ru",
    "botohub": "https://botohub.me/integration",
    "piarflow": "https://piarflow.com/api-docs",
    "tgrass": "https://tgrass.space/integration",
    "trafsly": "https://trafsly.com/api-docs",
}


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
        settings: Settings | None = None,
    ) -> OpResult:
        effective = settings or self._settings
        ctx.settings = effective
        enabled = await enabled_providers(session, effective)
        # Provider checks are network round trips (up to OP_TIMEOUT_SEC each): release
        # the SQLite write lock before making them.
        await commit_before_io()
        for name in CASCADE:
            if name not in enabled:
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
        TrafslyAdapter(settings),
        ManualAdapter(settings),
    ]


def provider_configured(name: str, settings: Settings) -> bool:
    """Whether the provider has credentials/channels and would do real work."""
    if name == "flyer":
        return bool(settings.flyer_api_key.strip())
    if name == "subgram":
        return bool(settings.subgram_api_key.strip())
    if name == "botohub":
        return bool(settings.botohub_api_key.strip())
    if name == "piarflow":
        return bool(settings.piarflow_api_key.strip())
    if name == "tgrass":
        return bool(settings.tgrass_api_key.strip() or settings.tgrass_channels.strip())
    if name == "trafsly":
        return bool(settings.trafsly_api_key.strip())
    if name == "manual":
        return bool(settings.parse_channel_list(settings.manual_op_channels))
    return False


async def enabled_providers(session: AsyncSession, settings: Settings) -> set[str]:
    defaults = {
        "flyer": settings.flyer_enabled,
        "subgram": settings.subgram_enabled,
        "botohub": settings.botohub_enabled,
        "piarflow": settings.piarflow_enabled,
        "tgrass": settings.tgrass_enabled,
        "trafsly": settings.trafsly_enabled,
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
