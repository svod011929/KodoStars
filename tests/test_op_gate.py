import pytest

from app.op.base import OpContext, OpResult, Sponsor
from app.op.gate import OpGate


class _Stub:
    def __init__(self, name: str, result: OpResult) -> None:
        self.name = name
        self.result = result
        self.calls = 0

    async def check(self, user: OpContext) -> OpResult:
        self.calls += 1
        return self.result

    async def verify(self, user: OpContext) -> OpResult:
        return await self.check(user)


@pytest.mark.asyncio
async def test_gate_blocks_on_piarflow(session, settings) -> None:
    pf = _Stub(
        "piarflow",
        OpResult.blocked("piarflow", [Sponsor(title="Ch", url="https://t.me/x")]),
    )
    gate = OpGate(settings, [pf])
    ctx = OpContext(1, 1, "A", None, "ru", False)
    result = await gate.enforce(ctx, session)
    assert result.allowed is False
    assert result.provider == "piarflow"
    assert pf.calls == 1


@pytest.mark.asyncio
async def test_gate_fail_open_continues(session, settings) -> None:
    pf = _Stub("piarflow", OpResult.fail_open_result("piarflow", "timeout"))
    gate = OpGate(settings, [pf])
    result = await gate.enforce(OpContext(1, 1, "A", None, "ru", False), session)
    assert result.allowed is True
    assert result.provider == "gate"


@pytest.mark.asyncio
async def test_gate_skip_when_disabled(session, settings) -> None:
    settings.piarflow_enabled = False
    pf = _Stub("piarflow", OpResult.blocked("piarflow", [Sponsor(title="Ch", url="https://t.me/x")]))
    gate = OpGate(settings, [pf])
    result = await gate.enforce(OpContext(1, 1, "A", None, "ru", False), session)
    assert result.allowed is True
    assert pf.calls == 0
