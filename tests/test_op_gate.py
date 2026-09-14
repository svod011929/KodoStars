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
async def test_gate_skips_then_blocks(session, settings) -> None:
    flyer = _Stub("flyer", OpResult.skip("flyer", "no key"))
    sub = _Stub(
        "subgram",
        OpResult.blocked("subgram", [Sponsor(title="Ch", url="https://t.me/x")]),
    )
    rest = [
        _Stub(name, OpResult.ok(name))
        for name in ("botohub", "piarflow", "tgrass", "manual")
    ]
    gate = OpGate(settings, [flyer, sub, *rest])
    ctx = OpContext(1, 1, "A", None, "ru", False)
    result = await gate.enforce(ctx, session)
    assert result.allowed is False
    assert result.provider == "subgram"
    assert flyer.calls == 1
    assert sub.calls == 1
    assert rest[0].calls == 0


@pytest.mark.asyncio
async def test_gate_fail_open_continues(session, settings) -> None:
    flyer = _Stub("flyer", OpResult.fail_open_result("flyer", "timeout"))
    others = [
        _Stub(name, OpResult.ok(name))
        for name in ("subgram", "botohub", "piarflow", "tgrass", "manual")
    ]
    gate = OpGate(settings, [flyer, *others])
    result = await gate.enforce(
        OpContext(1, 1, "A", None, "ru", False),
        session,
    )
    assert result.allowed is True
    assert result.provider == "gate"
