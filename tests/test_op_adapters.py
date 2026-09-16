"""OP adapters against the documented provider contracts.

Sample payloads are taken from the official docs:
Flyer https://api.flyerhubs.com/, BotoHub https://botohub.me/integration,
TGrass https://tgrass.space/integration, PiarFlow https://piarflow.com/api-docs,
Trafsly https://trafsly.com/api-docs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.config import Settings
from app.op import botohub, flyer, piarflow, tgrass, trafsly
from app.op.base import BoundedCache, OpContext, title_from_link
from app.op.botohub import BotoHubAdapter
from app.op.flyer import FlyerAdapter
from app.op.manual import (
    ManualAdapter,
    chat_ref,
    check_channels,
    format_channel_entry,
    parse_channel_entry,
    validate_channel_entry,
)
from app.op.piarflow import PiarFlowAdapter
from app.op.subgram import SubGramAdapter
from app.op.tgrass import TGrassAdapter
from app.op.trafsly import TrafslyAdapter

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
    # Order of link/title does not matter.
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


@pytest.mark.asyncio
async def test_adapters_skip_without_keys(settings) -> None:
    ctx = OpContext(1, 1, "A", None, "ru", False)
    for adapter in (
        FlyerAdapter(settings),
        SubGramAdapter(settings),
        BotoHubAdapter(settings),
        PiarFlowAdapter(settings),
        TGrassAdapter(settings),
        TrafslyAdapter(settings),
        ManualAdapter(settings),
    ):
        result = await adapter.check(ctx)
        assert result.skipped is True
        assert result.allowed is True


def test_legacy_provider_urls_are_upgraded() -> None:
    settings = _settings(
        flyer_api_url="https://api.flyerservice.io",
        botohub_api_url="https://botohub.me/api/v1",
        tgrass_api_url="https://api.tgrass.online/v1/",
    )
    assert settings.flyer_api_url == "https://api.flyerhubs.com"
    assert settings.botohub_api_url == "https://botohub.me"
    assert settings.tgrass_api_url == "https://tgrass.space"
    custom = _settings(botohub_api_url="https://proxy.example/botohub")
    assert custom.botohub_api_url == "https://proxy.example/botohub"


def test_title_from_link_and_bounded_cache() -> None:
    assert title_from_link("https://t.me/cryptonews", "x") == "@cryptonews"
    assert title_from_link("https://t.me/SomeBot?start=ref_xyz", "x") == "@SomeBot"
    assert title_from_link("https://telegram.me/channel1", "x") == "@channel1"
    assert title_from_link("https://t.me/+AbCdEf", "Спонсор") == "Спонсор"
    assert title_from_link("https://t.me/c/123/4", "Спонсор") == "Спонсор"
    assert title_from_link("https://example.com", "Спонсор") == "Спонсор"

    cache: BoundedCache[int, str] = BoundedCache(max_size=2)
    cache.set(1, "a")
    cache.set(2, "b")
    cache.set(3, "c")
    assert cache.get(1) is None and cache.get(3) == "c" and len(cache) == 2


# --- Flyer ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flyer_sub_key_uses_check_and_flyer_sends_its_own_message(monkeypatch) -> None:
    state = {"skip": False}

    def responder(url, body, headers):
        assert body["key"] == "FL-key"
        if url.endswith("/get_me"):
            return 200, {"type": "sub", "status": True, "webhook": None, "key_number": 1, "bot_id": 2}
        if url.endswith("/check"):
            assert body["user_id"] == 1 and body["language_code"] == "ru"
            assert body["message"]["button_channel"]
            return 200, {"skip": state["skip"], "attached_at": 1700000000}
        raise AssertionError(f"unexpected call {url}")

    http = FakeHttp(responder)
    monkeypatch.setattr(flyer, "post_json", http)
    adapter = FlyerAdapter(_settings(flyer_api_key="FL-key"))

    blocked = await adapter.check(_ctx())
    assert blocked.allowed is False and blocked.sponsors == []
    assert "Flyer" in blocked.message
    assert http.urls() == ["https://api.flyerhubs.com/get_me", "https://api.flyerhubs.com/check"]

    state["skip"] = True
    passed = await adapter.verify(_ctx())
    assert passed.allowed is True
    assert http.urls().count("https://api.flyerhubs.com/get_me") == 1  # key type cached


@pytest.mark.asyncio
async def test_flyer_tasks_key_parses_links_and_statuses(monkeypatch) -> None:
    tasks = [
        {
            "signature": "s1",
            "task": "subscribe channel",
            "price": 1.5,
            "links": ["https://t.me/first"],
            "name": "First",
            "status": "incomplete",
            "resource_id": -100,
        },
        {
            "signature": "s2",
            "task": "start bot",
            "links": ["https://t.me/somebot?start=x"],
            "name": None,
            "status": "abort",
        },
        {
            "signature": "s3",
            "task": "subscribe channel",
            "links": ["https://t.me/done"],
            "name": "Done",
            "status": "complete",
        },
        {
            "signature": "s4",
            "task": "subscribe channel",
            "links": ["https://t.me/wait"],
            "name": "Wait",
            "status": "waiting",
        },
        {
            "signature": "s5",
            "task": "subscribe channel",
            "links": [],
            "name": "Broken",
            "status": "incomplete",
        },
    ]

    def responder(url, body, headers):
        if url.endswith("/get_me"):
            return 200, {"type": "tasks", "status": True}
        if url.endswith("/get_tasks"):
            assert body["limit"] == 5
            return 200, {"result": tasks, "attached_at": 1}
        raise AssertionError(url)

    monkeypatch.setattr(flyer, "post_json", FakeHttp(responder))
    result = await FlyerAdapter(_settings(flyer_api_key="FL-key")).check(_ctx())
    assert result.allowed is False
    assert [(s.title, s.url, s.kind) for s in result.sponsors] == [
        ("First", "https://t.me/first", "channel"),
        ("Запустить бота", "https://t.me/somebot?start=x", "bot"),
    ]

    tasks[:] = [dict(item, status="complete") for item in tasks]
    assert (await FlyerAdapter(_settings(flyer_api_key="FL-key")).check(_ctx())).allowed is True


@pytest.mark.asyncio
async def test_flyer_falls_back_to_tasks_on_prohibited_method_and_fails_open_on_error(monkeypatch) -> None:
    def responder(url, body, headers):
        if url.endswith("/get_me"):
            return 500, "boom"
        if url.endswith("/check"):
            return 200, {"error": "Prohibited method for a bot type"}
        if url.endswith("/get_tasks"):
            return 200, {"result": []}
        raise AssertionError(url)

    http = FakeHttp(responder)
    monkeypatch.setattr(flyer, "post_json", http)
    adapter = FlyerAdapter(_settings(flyer_api_key="FL-key"))
    assert (await adapter.check(_ctx())).allowed is True
    assert http.urls()[-2:] == ["https://api.flyerhubs.com/check", "https://api.flyerhubs.com/get_tasks"]

    def failing(url, body, headers):
        if url.endswith("/get_me"):
            return 200, {"type": "sub"}
        return 200, {"error": "Key not found"}

    monkeypatch.setattr(flyer, "post_json", FakeHttp(failing))
    result = await FlyerAdapter(_settings(flyer_api_key="FL-key")).check(_ctx())
    assert result.fail_open is True and result.allowed is True and "Key not found" in result.message


# --- BotoHub --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_botohub_extended_contract(monkeypatch) -> None:
    payload = {
        "tasks": [
            {"url": "https://telegram.me/channel1", "resource_id": "-1001234567890", "completed": True},
            {
                "url": "https://telegram.me/some_bot?start=ref",
                "resource_id": "7000000000",
                "completed": False,
            },
        ],
        "completed": False,
        "skip": False,
    }

    def responder(url, body, headers):
        assert url == "https://botohub.me/get-tasks-extended"
        assert headers == {"Auth": "bh-token", "Content-Type": "application/json"}
        assert body == {"chat_id": 1, "max_op": 3}
        return 200, payload

    http = FakeHttp(responder)
    monkeypatch.setattr(botohub, "post_json", http)
    adapter = BotoHubAdapter(_settings(botohub_api_key="bh-token", botohub_max_op=3))

    result = await adapter.check(_ctx())
    assert result.allowed is False
    assert [(s.title, s.url, s.kind) for s in result.sponsors] == [
        ("@some_bot", "https://telegram.me/some_bot?start=ref", "bot")
    ]

    payload["tasks"][1]["completed"] = True
    payload["completed"] = True
    assert (await adapter.verify(_ctx())).allowed is True
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_botohub_skip_plain_format_and_errors(monkeypatch) -> None:
    answers = iter(
        [
            (200, {"tasks": [], "completed": False, "skip": True}),
            (
                200,
                {
                    "tasks": ["https://telegram.me/channel1", "https://telegram.me/channel2"],
                    "completed": False,
                    "skip": False,
                },
            ),
            (200, {"tasks": []}),
            (401, {"error": "Unauthorized"}),
        ]
    )
    monkeypatch.setattr(botohub, "post_json", FakeHttp(lambda url, body, headers: next(answers)))
    adapter = BotoHubAdapter(_settings(botohub_api_key="bh-token"))
    assert (await adapter.check(_ctx())).allowed is True  # skip
    plain = await adapter.check(_ctx())
    assert plain.allowed is False and [s.url for s in plain.sponsors] == [
        "https://telegram.me/channel1",
        "https://telegram.me/channel2",
    ]
    assert (await adapter.check(_ctx())).allowed is True  # blocked bot → empty list → pass
    unauthorized = await adapter.check(_ctx())
    assert unauthorized.fail_open is True and "Unauthorized" in unauthorized.message


# --- TGrass ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tgrass_offers_contract(monkeypatch) -> None:
    payload = {
        "status": "not_ok",
        "offers": [
            {
                "name": "Канал о крипте",
                "link": "https://t.me/cryptochannel",
                "subscribed": True,
                "type": "channel",
                "channel_id": None,
                "offer_id": 1012,
            },
            {
                "name": None,
                "link": "https://t.me/technews",
                "subscribed": False,
                "type": "channel",
                "channel_id": "-10566012393",
                "offer_id": 1054,
            },
            {
                "name": "Бот",
                "link": "https://t.me/somebot",
                "subscribed": False,
                "type": "bot",
                "channel_id": None,
                "offer_id": 2,
            },
        ],
        "description": "not subscribed",
    }

    def responder(url, body, headers):
        assert url == "https://tgrass.space/offers"
        assert headers["Auth"] == "tg-key"
        assert body == {
            "tg_user_id": 1,
            "is_premium": True,
            "lang": "ru",
            "tg_login": "daniel",
            "offers_limit": 4,
        }
        return 200, payload

    monkeypatch.setattr(tgrass, "post_json", FakeHttp(responder))
    adapter = TGrassAdapter(_settings(tgrass_api_key="tg-key", tgrass_offers_limit=4))

    result = await adapter.check(_ctx())
    assert result.allowed is False
    assert [(s.title, s.url, s.kind) for s in result.sponsors] == [
        ("@technews", "https://t.me/technews", "channel"),
        ("Бот", "https://t.me/somebot", "bot"),
    ]

    payload["status"] = "ok"
    assert (await adapter.verify(_ctx())).allowed is True
    payload["status"] = "no_offers"
    payload["offers"] = []
    assert (await adapter.check(_ctx())).allowed is True


@pytest.mark.asyncio
async def test_tgrass_errors_fail_open_but_local_channels_still_checked(monkeypatch) -> None:
    monkeypatch.setattr(
        tgrass, "post_json", FakeHttp(lambda url, body, headers: (401, {"detail": "Auth token not provided"}))
    )
    api_only = await TGrassAdapter(_settings(tgrass_api_key="tg-key")).check(_ctx())
    assert api_only.fail_open is True and api_only.allowed is True

    # No bot in the context → local channels cannot be verified → they are shown as required.
    with_channels = await TGrassAdapter(_settings(tgrass_api_key="tg-key", tgrass_channels="@kodo")).check(
        _ctx()
    )
    assert with_channels.allowed is False
    assert [s.url for s in with_channels.sponsors] == ["https://t.me/kodo"]


# --- PiarFlow -------------------------------------------------------------------------


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
    # Links are forgotten after success → next verify re-fetches sponsors.
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


# --- Trafsly --------------------------------------------------------------------------


TRAFSLY_WARNING = {
    "status": "warning",
    "sponsors": [
        {
            "ads_id": 10421,
            "link": "https://t.me/cryptonews",
            "resource_type": "channel",
            "title": "Crypto News",
            "status": "unsubscribed",
        },
        {
            "ads_id": 10422,
            "link": "https://t.me/SomeBot?start=ref_xyz",
            "resource_type": "bot",
            "title": "",
            "status": "unsubscribed",
        },
        {
            "ads_id": 10423,
            "link": "https://t.me/hold",
            "resource_type": "channel",
            "title": "Hold",
            "status": "hold",
        },
    ],
}


@pytest.mark.asyncio
async def test_trafsly_get_sponsors_and_confirm(monkeypatch) -> None:
    confirmed: dict[int, bool] = {10421: True, 10422: False}

    def responder(url, body, headers):
        assert headers == {"Auth": "at_secret", "Content-Type": "application/json"}
        if url == "https://api.trafsly.com/api/v1/get-sponsors":
            assert body == {
                "user_id": 1,
                "chat_id": 1,
                "is_premium": True,
                "max_sponsors": 5,
                "action": "subscribe",
                "language_code": "ru",
                "first_name": "Даниил",
                "username": "daniel",
            }
            return 200, TRAFSLY_WARNING
        if url == "https://api.trafsly.com/api/v1/confirm-subscription":
            ads_id = body["ads_id"]
            assert body["user_id"] == 1 and ads_id in confirmed
            if confirmed[ads_id]:
                return 200, {
                    "status": "ok",
                    "subscribed": True,
                    "credited": 1.1,
                    "credit_status": "paid",
                    "message": "Subscription confirmed",
                }
            return 200, {"status": "warning", "subscribed": False, "message": "User is not subscribed"}
        raise AssertionError(url)

    http = FakeHttp(responder)
    monkeypatch.setattr(trafsly, "post_json", http)
    adapter = TrafslyAdapter(_settings(trafsly_api_key="at_secret"))

    result = await adapter.check(_ctx())
    assert result.allowed is False
    assert [(s.title, s.url, s.kind) for s in result.sponsors] == [
        ("Crypto News", "https://t.me/cryptonews", "channel"),
        ("@SomeBot", "https://t.me/SomeBot?start=ref_xyz", "bot"),
    ]

    partial = await adapter.verify(_ctx())
    assert partial.allowed is False
    assert [s.url for s in partial.sponsors] == ["https://t.me/SomeBot?start=ref_xyz"]
    confirm_calls = [body["ads_id"] for url, body, _ in http.calls if url.endswith("confirm-subscription")]
    assert confirm_calls == [10421, 10422]

    confirmed[10422] = True
    done = await adapter.verify(_ctx())
    assert done.allowed is True
    # Only the still-pending ads_id was confirmed the second time.
    assert [body["ads_id"] for url, body, _ in http.calls if url.endswith("confirm-subscription")] == [
        10421,
        10422,
        10422,
    ]


@pytest.mark.asyncio
async def test_trafsly_ok_status_banned_user_and_stale_orders(monkeypatch) -> None:
    monkeypatch.setattr(
        trafsly,
        "post_json",
        FakeHttp(
            lambda url, body, headers: (200, {"status": "ok", "sponsors": [], "message": "User can proceed"})
        ),
    )
    assert (await TrafslyAdapter(_settings(trafsly_api_key="at_x")).check(_ctx())).allowed is True

    def stale(url, body, headers):
        if url.endswith("get-sponsors"):
            return 200, TRAFSLY_WARNING
        if body["ads_id"] == 10421:
            return 200, {"status": "warning", "subscribed": False, "message": "Sponsor was not shown"}
        raise AssertionError("second ads_id must not be confirmed after a stale answer")

    http = FakeHttp(stale)
    monkeypatch.setattr(trafsly, "post_json", http)
    adapter = TrafslyAdapter(_settings(trafsly_api_key="at_x"))
    await adapter.check(_ctx())
    refreshed = await adapter.verify(_ctx())
    assert refreshed.allowed is False
    assert http.urls().count("https://api.trafsly.com/api/v1/get-sponsors") == 2

    def banned(url, body, headers):
        if url.endswith("get-sponsors"):
            return 200, TRAFSLY_WARNING
        return 200, {"status": "warning", "subscribed": False, "message": "User is banned"}

    monkeypatch.setattr(trafsly, "post_json", FakeHttp(banned))
    adapter = TrafslyAdapter(_settings(trafsly_api_key="at_x"))
    await adapter.check(_ctx())
    assert (await adapter.verify(_ctx())).allowed is True


@pytest.mark.asyncio
async def test_trafsly_errors_fail_open(monkeypatch) -> None:
    monkeypatch.setattr(
        trafsly,
        "post_json",
        FakeHttp(lambda url, body, headers: (401, {"detail": "Invalid or inactive Bot API Key"})),
    )
    result = await TrafslyAdapter(_settings(trafsly_api_key="at_x")).check(_ctx())
    assert result.fail_open is True and result.allowed is True and "Invalid" in result.message

    async def exploding(url, *, json, headers=None, timeout_sec=8.0):
        raise TimeoutError("timeout")

    monkeypatch.setattr(trafsly, "post_json", exploding)
    result = await TrafslyAdapter(_settings(trafsly_api_key="at_x")).check(_ctx())
    assert result.fail_open is True and "timeout" in result.message
