from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ProviderState, User
from app.db.txn import commit_before_io
from app.op.base import OpAdapter, OpContext, OpResult
from app.op.piarflow import PiarFlowAdapter
from app.op.tgrass import TgrassAdapter
from app.services.devices import op_access_block_reason

log = structlog.get_logger("kodostars.op")

# Admin toggle order. Runtime cascade for a user depends on twin/device status:
# verified → PiarFlow then Tgrass; unverified → Tgrass only.
CASCADE: tuple[str, ...] = ("piarflow", "tgrass")

PROVIDER_TITLES: dict[str, str] = {
    "piarflow": "PiarFlow",
    "tgrass": "Tgrass",
}

PROVIDER_DOCS: dict[str, str] = {
    "piarflow": "https://piarflow.com/api-docs",
    "tgrass": "https://tgrass.space/integration",
}


def providers_for_user(user: User, settings: Settings) -> tuple[str, ...]:
    """Which OP providers to run for this user.

    * Twin/device OK → PiarFlow first, then Tgrass.
    * Not verified (or twink blocked for OP) → Tgrass only.
    """
    if op_access_block_reason(user, settings) is None:
        return ("piarflow", "tgrass")
    return ("tgrass",)


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
        providers: Sequence[str] | None = None,
        user: User | None = None,
    ) -> OpResult:
        effective = settings or self._settings
        ctx.settings = effective
        enabled = await enabled_providers(session, effective)
        await commit_before_io()
        if providers is not None:
            names = tuple(providers)
        elif user is not None:
            names = providers_for_user(user, effective)
        else:
            names = CASCADE
        paid_links: list[str] = []
        for name in names:
            if name not in enabled:
                continue
            adapter = self._by_name.get(name)
            if adapter is None:
                continue
            result = await (adapter.verify(ctx) if verify else adapter.check(ctx))
            if result.paid_links:
                paid_links.extend(result.paid_links)
            log.info(
                "op_provider_result",
                provider=name,
                allowed=result.allowed,
                skipped=result.skipped,
                fail_open=result.fail_open,
                sponsors=len(result.sponsors),
                paid=len(result.paid_links),
            )
            if result.skipped or result.fail_open:
                continue
            if not result.allowed:
                result.paid_links = list(dict.fromkeys(paid_links))
                return result
        return OpResult.ok("gate", paid_links=list(dict.fromkeys(paid_links)))


def default_adapters(settings: Settings) -> list[OpAdapter]:
    return [PiarFlowAdapter(settings), TgrassAdapter(settings)]


def provider_configured(name: str, settings: Settings) -> bool:
    if name == "tgrass":
        return bool(settings.tgrass_api_key.strip())
    if name == "piarflow":
        return bool(settings.piarflow_api_key.strip())
    return False


async def enabled_providers(session: AsyncSession, settings: Settings) -> set[str]:
    defaults = {
        "tgrass": settings.tgrass_enabled,
        "piarflow": settings.piarflow_enabled,
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
