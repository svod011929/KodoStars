"""Tgrass adapter contract + unsubscribe webhook."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.db.models import LedgerKind, User
from app.op import tgrass as tgrass_mod
from app.op.base import OpContext
from app.op.tgrass import TgrassAdapter
from app.services import ledger, tgrass_webhook
from app.services.events import drain
from tests.test_op_adapters import FakeHttp


def _ctx(user_id: int = 1) -> OpContext:
    return OpContext(user_id, user_id, "Даниил", "daniel", "ru", True)


def _settings(**overrides: Any) -> Settings:
    base = {
        "admin_ids_raw": "1",
        "database_url": "sqlite+aiosqlite://",
        "tgrass_api_key": "tg-key",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_tgrass_contract_blocks_and_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = {
        "first": {
            "status": "not_ok",
            "description": "need sub",
            "offers": [
                {
                    "name": "Канал",
                    "link": "https://t.me/cryptochannel",
                    "subscribed": False,
                    "type": "channel",
                    "offer_id": 1012,
                },
                {
                    "name": "Done",
                    "link": "https://t.me/done",
                    "subscribed": True,
                    "type": "channel",
                    "offer_id": 1,
                },
            ],
        },
        "second": {"status": "ok", "description": "subscribed to all", "offers": []},
    }
    calls = {"n": 0}

    def responder(url: str, body: dict, headers: dict | None):
        assert url == "https://tgrass.space/offers"
        assert headers["Auth"] == "tg-key"
        assert "Bearer" not in headers.get("Auth", "")
        assert body["tg_user_id"] == 1
        assert body["is_premium"] is True
        assert body["lang"] == "ru"
        assert body["tg_login"] == "daniel"
        assert body["offers_limit"] == 5
        calls["n"] += 1
        return 200, payloads["first"] if calls["n"] == 1 else payloads["second"]

    fake = FakeHttp(responder)
    monkeypatch.setattr(tgrass_mod, "post_json", fake)
    adapter = TgrassAdapter(_settings())
    blocked = await adapter.check(_ctx())
    assert blocked.allowed is False
    assert len(blocked.sponsors) == 1
    assert blocked.sponsors[0].url == "https://t.me/cryptochannel"
    assert blocked.sponsors[0].title == "Канал"

    ok = await adapter.verify(_ctx())
    assert ok.allowed is True
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_tgrass_skip_without_key() -> None:
    adapter = TgrassAdapter(_settings(tgrass_api_key=""))
    result = await adapter.check(_ctx())
    assert result.skipped is True
    assert result.allowed is True


@pytest.mark.asyncio
async def test_tgrass_unsub_webhook_penalty(session, settings) -> None:
    settings.tgrass_unsub_penalty = 7
    user = User(id=55, first_name="A")
    session.add(user)
    await session.flush()
    await ledger.credit(session, user_id=55, amount=20, kind=LedgerKind.TASK)

    first = await tgrass_webhook.handle_webhook(
        session,
        payload={
            "tg_user_id": 55,
            "offer_link": "https://t.me/telegram",
            "status": "unsubscribed",
        },
        settings=settings,
    )
    assert first.processed is True and first.penalty == 7
    assert await ledger.get_balance(session, 55) == 13
    refreshed = await session.get(User, 55)
    assert refreshed.last_op_ok_at is None
    events = drain(session)
    assert any(e.name == "tgrass_unsubscribed" for e in events)

    dup = await tgrass_webhook.handle_webhook(
        session,
        payload={
            "tg_user_id": 55,
            "offer_link": "https://t.me/telegram",
            "status": "unsubscribed",
        },
        settings=settings,
    )
    assert dup.duplicate is True and dup.processed is False
    assert await ledger.get_balance(session, 55) == 13


@pytest.mark.asyncio
async def test_tgrass_task_webhook_ack(session, settings) -> None:
    result = await tgrass_webhook.handle_webhook(
        session,
        payload={
            "tg_user_id": 9,
            "offer_id": 42,
            "offer_link": "https://t.me/example",
            "timestamp": "2026-05-29T12:00:00+00:00",
        },
        settings=settings,
    )
    assert result.kind == "task" and result.processed is True
