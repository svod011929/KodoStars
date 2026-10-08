"""BotoHub Views client: fail-open impressions + cooldown."""

from __future__ import annotations

import asyncio
import inspect
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


@pytest.mark.asyncio
async def test_scheduled_task_is_kept_alive_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    release = asyncio.Event()

    async def fake_post(*_a: Any, **_k: Any) -> tuple[int, dict]:
        await release.wait()
        return 200, {"SendPostResult": 1}

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    botohub_views.schedule_ad(5, _settings())
    await asyncio.sleep(0)
    pending = [task for task in botohub_views._background if task.get_name() == "botohub-ad-5"]
    assert len(pending) == 1
    release.set()
    await pending[0]
    assert pending[0] not in botohub_views._background


def test_spawn_without_loop_closes_coroutine() -> None:
    async def never() -> None:
        return None

    coro = never()
    botohub_views._spawn(coro, name="no-loop")
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


@pytest.mark.asyncio
async def test_concurrent_ads_for_one_user_send_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    release = asyncio.Event()

    async def fake_post(*_a: Any, **_k: Any) -> tuple[int, dict]:
        nonlocal calls
        calls += 1
        await release.wait()
        return 200, {"SendPostResult": 1}

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    settings = _settings()
    first = asyncio.create_task(botohub_views.maybe_send_ad(11, settings))
    await asyncio.sleep(0)
    second = asyncio.create_task(botohub_views.maybe_send_ad(11, settings))
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=2)
    assert sorted(results) == [False, True]
    assert calls == 1


@pytest.mark.asyncio
async def test_failed_ad_releases_the_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter([{"SendPostResult": 8}, {"SendPostResult": 1}])

    async def fake_post(*_a: Any, **_k: Any) -> tuple[int, dict]:
        return 200, next(results)

    monkeypatch.setattr(botohub_views.op_http, "post_json", fake_post)
    settings = _settings()
    assert await botohub_views.maybe_send_ad(12, settings) is False
    assert await botohub_views.maybe_send_ad(12, settings) is True
