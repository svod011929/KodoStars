"""OP adapters against the documented PiarFlow contract + channel helpers for tasks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.config import Settings
from app.op import piarflow
from app.op.base import OpContext, title_from_link
from app.op.gate import default_adapters
from app.op.piarflow import PiarFlowAdapter
from app.services.channels import (
    chat_ref,
    check_channels,
    format_channel_entry,
    parse_channel_entry,
    validate_channel_entry,
)

Responder = Callable[[str, dict[str, Any], dict[str, str] | None], tuple[int, Any]]


class FakeHttp:
    """Replaces ``post_json`` inside an adapter module and records every call."""

    def __init__(self, responder: Responder) -> None:
        self.responder = responder
        self.calls: list[tuple[str, dict[str, Any], dict[str, str] | None]] = []

    async def __call__(self, url: str, *, json: dict[str, Any], headers=None, timeout_sec: float = 8.0):
        self.calls.append((url, json, headers))
        return self.responder(url, json, headers)

    def urls(self) -> list[str]:
        return [url for url, _, _ in self.calls]


def _ctx(user_id: int = 1) -> OpContext:
    return OpContext(user_id, user_id, "Даниил", "daniel", "ru", True)


def _settings(**overrides) -> Settings:
    return Settings(admin_ids_raw="1", database_url="sqlite+aiosqlite://", **overrides)


def test_channel_entry_parsing_and_validation() -> None:
    public = parse_channel_entry("@kodo")
    assert (public.chat, public.url, public.title, public.is_private) == (
        "@kodo",
        "https://t.me/kodo",
        "@kodo",
        False,
    )
    titled = parse_channel_entry("@kodo|Наш канал")
    assert titled.title == "Наш канал" and titled.url == "https://t.me/kodo"
    private = parse_channel_entry("-1001234567890|https://t.me/+AbCdEf|VIP канал")
    assert private.chat == -1001234567890 and private.is_private and private.has_join_link
    assert private.url == "https://t.me/+AbCdEf" and private.title == "VIP канал"
    swapped = parse_channel_entry("-1001234567890|VIP|https://t.me/+AbCdEf")
    assert (swapped.url, swapped.title) == ("https://t.me/+AbCdEf", "VIP")
    bare_private = parse_channel_entry("-1001234567890")
    assert bare_private.has_join_link is False and bare_private.url == "https://t.me/c/1234567890"

    assert validate_channel_entry("@kodo") is None
    assert validate_channel_entry("-1001234567890|https://t.me/+AbCdEf|VIP") is None
    assert "пригласительная ссылка" in validate_channel_entry("-1001234567890")
    assert "запятая" in validate_channel_entry("@a,@b")
    assert "нужен @username" in validate_channel_entry("kodo")
    assert "нужен @username" in validate_channel_entry("-12345")
    assert "Telegram" in validate_channel_entry("@kodo|https://example.com/x")
    assert "одну ссылку" in validate_channel_entry("@kodo|https://t.me/a|https://t.me/b")

    assert format_channel_entry(-100123, "https://t.me/+x", "A, B|C") == "-100123|https://t.me/+x|A  B/C"
    assert chat_ref("-1001234567890|https://t.me/+AbCdEf") == -1001234567890
    assert chat_ref("@kodo|Title") == "@kodo"


@pytest.mark.asyncio
async def test_check_channels_uses_entry_link_and_title() -> None:
    sponsors = await check_channels(None, 1, ["@kodo|Наш канал", "-100555|https://t.me/+Paid|Клуб"])
    assert [(s.title, s.url) for s in sponsors] == [
        ("Наш канал", "https://t.me/kodo"),
        ("Клуб", "https://t.me/+Paid"),
    ]


def test_default_adapters_only_piarflow() -> None:
    adapters = default_adapters(_settings())
    assert [a.name for a in adapters] == ["piarflow"]


def test_title_from_link() -> None:
    assert title_from_link("https://t.me/cryptonews", "x") == "@cryptonews"


@pytest.mark.asyncio
async def test_piarflow_contract(monkeypatch) -> None:
    sponsors_payload = {
        "status": "ok",
        "message": "Sponsors returned",
        "sponsors": [
            {"link": "https://t.me/cryptonews", "status": "unsubscribed", "price": 5},
            {"link": "https://t.me/PiarFlowBot", "status": "not_counted", "price": 0},
        ],
    }
    check_payload = {
        "status": "ok",
        "sponsors": [{"link": "https://t.me/cryptonews", "status": "subscribed"}],
    }

    def responder(url, body, headers):
        assert headers["Authorization"] == "Bearer pf-key"
        if url == "https://piarflow.com/v1/sponsors":
            assert body["user_id"] == 1 and body["chat_id"] == 1 and body["max_sponsors"] == 5
            assert body["first_name"] == "Даниил" and body["username"] == "daniel"
            assert body["language_code"] == "ru" and body["bio"] is None
            return 200, sponsors_payload
        if url == "https://piarflow.com/v1/sponsors/check":
            assert body == {"user_id": 1, "links": ["https://t.me/cryptonews"]}
            return 200, check_payload
        raise AssertionError(url)

    http = FakeHttp(responder)
    monkeypatch.setattr(piarflow, "post_json", http)
    adapter = PiarFlowAdapter(_settings(piarflow_api_key="pf-key"))

    result = await adapter.check(_ctx())
    assert result.allowed is False
    assert [(s.title, s.url) for s in result.sponsors] == [("@cryptonews", "https://t.me/cryptonews")]

    verified = await adapter.verify(_ctx())
    assert verified.allowed is True
    assert http.urls()[-1] == "https://piarflow.com/v1/sponsors/check"
    await adapter.verify(_ctx())
    assert http.urls()[-1] == "https://piarflow.com/v1/sponsors"


@pytest.mark.asyncio
async def test_piarflow_404_means_no_tasks_and_5xx_fails_open(monkeypatch) -> None:
    monkeypatch.setattr(
        piarflow,
        "post_json",
        FakeHttp(lambda url, body, headers: (404, {"status": "error", "message": "Not found"})),
    )
    assert (await PiarFlowAdapter(_settings(piarflow_api_key="pf")).check(_ctx())).allowed is True
    monkeypatch.setattr(
        piarflow,
        "post_json",
        FakeHttp(lambda url, body, headers: (429, {"status": "error", "message": "Too many"})),
    )
    result = await PiarFlowAdapter(_settings(piarflow_api_key="pf")).check(_ctx())
    assert result.fail_open is True and "Too many" in result.message
