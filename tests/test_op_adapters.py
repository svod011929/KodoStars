import pytest

from app.op.base import OpContext
from app.op.botohub import BotoHubAdapter
from app.op.flyer import FlyerAdapter
from app.op.manual import ManualAdapter
from app.op.piarflow import PiarFlowAdapter
from app.op.subgram import SubGramAdapter
from app.op.tgrass import TGrassAdapter


@pytest.mark.asyncio
async def test_adapters_skip_without_keys(settings) -> None:
    ctx = OpContext(1, 1, "A", None, "ru", False)
    for adapter in (
        FlyerAdapter(settings),
        SubGramAdapter(settings),
        BotoHubAdapter(settings),
        PiarFlowAdapter(settings),
        TGrassAdapter(settings),
        ManualAdapter(settings),
    ):
        result = await adapter.check(ctx)
        assert result.skipped is True
        assert result.allowed is True
