import pytest
from sqlalchemy import select

from app.db.models import PiarflowIssuedSub, PiarflowPaidSub, User
from app.op.base import OpContext, OpResult, Sponsor
from app.op.gate import OpGate, providers_for_user
from app.services import piarflow_quality


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
async def test_verified_user_runs_piarflow_then_tgrass(session, settings) -> None:
    settings.device_check_for_op = False
    settings.twink_block_op = False
    user = User(id=1, first_name="A")
    pf = _Stub("piarflow", OpResult.ok("piarflow"))
    tg = _Stub("tgrass", OpResult.ok("tgrass"))
    gate = OpGate(settings, [pf, tg])
    result = await gate.enforce(OpContext(1, 1, "A", None, "ru", False), session, user=user)
    assert result.allowed is True
    assert pf.calls == 1
    assert tg.calls == 1
    assert providers_for_user(user, settings) == ("piarflow", "tgrass")


@pytest.mark.asyncio
async def test_unverified_user_tgrass_only(session, settings) -> None:
    settings.device_check_enabled = True
    settings.device_check_for_op = True
    settings.web_public_url = "https://example.com"
    user = User(id=2, first_name="B")  # no device_verified_at
    pf = _Stub(
        "piarflow",
        OpResult.blocked("piarflow", [Sponsor(title="P", url="https://t.me/p")]),
    )
    tg = _Stub(
        "tgrass",
        OpResult.blocked("tgrass", [Sponsor(title="T", url="https://t.me/t")]),
    )
    gate = OpGate(settings, [pf, tg])
    result = await gate.enforce(OpContext(2, 2, "B", None, "ru", False), session, user=user)
    assert result.allowed is False
    assert result.provider == "tgrass"
    assert pf.calls == 0
    assert tg.calls == 1
    assert providers_for_user(user, settings) == ("tgrass",)


@pytest.mark.asyncio
async def test_gate_fail_open_continues(session, settings) -> None:
    settings.tgrass_enabled = False
    pf = _Stub("piarflow", OpResult.fail_open_result("piarflow", "timeout"))
    gate = OpGate(settings, [pf])
    result = await gate.enforce(OpContext(1, 1, "A", None, "ru", False), session)
    assert result.allowed is True
    assert result.provider == "gate"


@pytest.mark.asyncio
async def test_gate_skip_when_disabled(session, settings) -> None:
    settings.piarflow_enabled = False
    settings.tgrass_enabled = False
    pf = _Stub("piarflow", OpResult.blocked("piarflow", [Sponsor(title="Ch", url="https://t.me/x")]))
    gate = OpGate(settings, [pf])
    result = await gate.enforce(OpContext(1, 1, "A", None, "ru", False), session)
    assert result.allowed is True
    assert pf.calls == 0


@pytest.mark.asyncio
async def test_gate_records_each_provider_once(session, settings) -> None:
    settings.device_check_for_op = False
    settings.twink_block_op = False
    user = User(id=3, first_name="C")
    session.add(user)
    await session.flush()
    pf = _Stub(
        "piarflow",
        OpResult.ok("piarflow", paid_links=["https://t.me/pf-paid"]),
    )
    tg = _Stub(
        "tgrass",
        OpResult.blocked(
            "tgrass",
            [Sponsor(title="T", url="https://t.me/tg")],
            paid_links=["https://t.me/tg-paid"],
        ),
    )
    gate = OpGate(settings, [pf, tg])
    result = await gate.enforce(OpContext(3, 3, "C", None, "ru", False), session, user=user)
    assert result.allowed is False
    assert result.provider == "tgrass"
    assert pf.calls == 1 and tg.calls == 1

    issued = list((await session.execute(select(PiarflowIssuedSub))).scalars().all())
    paid = list((await session.execute(select(PiarflowPaidSub))).scalars().all())
    assert [(row.provider, row.offer_link, row.show_count) for row in issued] == [
        ("tgrass", "https://t.me/tg", 1)
    ]
    assert sorted((row.provider, row.offer_link) for row in paid) == [
        ("piarflow", "https://t.me/pf-paid"),
        ("tgrass", "https://t.me/tg-paid"),
    ]
    assert await piarflow_quality.paid_sub_count(session, 3) == 1
    assert "gate" not in {row.provider for row in paid}
