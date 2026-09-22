"""BotoHub Views client: fail-open impressions + cooldown."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services import botohub_views


def _settings(**kwargs: Any) -> Settings:
    base = {
        "bot_token": "000000000:PLACEHOLDER_TOKEN_REPLACE_ME",
        "admin_ids_raw": "1",
        "botohub_views_enabled": True,
        "botohub_views_token": "test-token",
        "botohub_views_cooldown_seconds": 60,
        "botohub_views_api_url": "https://views.botohub.me/ad/SendPost",
    }
    base.update(kwargs)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _clear() -> None:
    botohub_views.clear_ad_cooldowns()
    yield
    botohub_views.clear_ad_cooldowns()


@pytest.mark.asyncio
async def test_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[Any] = []

    async def fake_post(*_a: Any, **_k: Any) -> tuple[int, dict]:
        called.append(1)
        return 200, {"SendPostResult": 1}

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    assert await botohub_views.maybe_send_ad(1, _settings(botohub_views_enabled=False)) is False
    assert await botohub_views.maybe_send_hi(1, _settings(botohub_views_token="")) is False
    assert called == []


@pytest.mark.asyncio
async def test_success_sends_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_post(url: str, *, json: dict, headers: dict, timeout_sec: float) -> tuple[int, dict]:
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers
        return 200, {"SendPostResult": 1}

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    assert await botohub_views.maybe_send_hi(42, _settings()) is True
    assert seen["json"] == {"SendToChatId": 42, "hi": True}
    assert seen["headers"]["Authorization"] == "test-token"
    assert "Bearer" not in seen["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_fail_open_on_no_ads(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(*_a: Any, **_k: Any) -> tuple[int, dict]:
        return 200, {"SendPostResult": 8}

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    assert await botohub_views.maybe_send_ad(7, _settings()) is False


@pytest.mark.asyncio
async def test_fail_open_on_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(*_a: Any, **_k: Any) -> tuple[int, dict]:
        raise TimeoutError("boom")

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    assert await botohub_views.maybe_send_ad(7, _settings()) is False


@pytest.mark.asyncio
async def test_ad_cooldown_blocks_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_post(*_a: Any, **_k: Any) -> tuple[int, dict]:
        nonlocal calls
        calls += 1
        return 200, {"SendPostResult": 1}

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    settings = _settings(botohub_views_cooldown_seconds=60)
    assert await botohub_views.maybe_send_ad(9, settings) is True
    assert await botohub_views.maybe_send_ad(9, settings) is False
    assert calls == 1
    # hi ignores local cooldown
    assert await botohub_views.maybe_send_hi(9, settings) is True
    assert calls == 2


@pytest.mark.asyncio
async def test_ad_payload_hi_false(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_post(_url: str, *, json: dict, headers: dict, timeout_sec: float) -> tuple[int, dict]:
        seen["json"] = json
        return 200, {"SendPostResult": 1}

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    assert await botohub_views.maybe_send_ad(3, _settings()) is True
    assert seen["json"]["hi"] is False
