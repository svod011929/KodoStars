from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from aiogram import Bot

if TYPE_CHECKING:
    from app.config import Settings


# Admin toggle order. Imported by the gate and by traffic stats (the gate records
# each adapter result, so stats must not import the gate module).
CASCADE: tuple[str, ...] = ("piarflow", "tgrass")


@dataclass(slots=True)
class Sponsor:
    title: str
    url: str
    kind: str = "channel"


@dataclass(slots=True)
class OpResult:
    allowed: bool
    provider: str
    skipped: bool = False
    fail_open: bool = False
    message: str = ""
    sponsors: list[Sponsor] = field(default_factory=list)
    # PiarFlow links with status ``subscribed`` (reward credited by the integration).
    paid_links: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls, provider: str, message: str = "", *, paid_links: list[str] | None = None) -> OpResult:
        return cls(allowed=True, provider=provider, message=message, paid_links=list(paid_links or []))

    @classmethod
    def blocked(
        cls,
        provider: str,
        sponsors: list[Sponsor],
        message: str = "",
        *,
        paid_links: list[str] | None = None,
    ) -> OpResult:
        return cls(
            allowed=False,
            provider=provider,
            sponsors=sponsors,
            message=message,
            paid_links=list(paid_links or []),
        )

    @classmethod
    def skip(cls, provider: str, reason: str) -> OpResult:
        return cls(allowed=True, provider=provider, skipped=True, message=reason)

    @classmethod
    def fail_open_result(cls, provider: str, error: str) -> OpResult:
        return cls(allowed=True, provider=provider, fail_open=True, message=error)


@dataclass(slots=True)
class OpContext:
    user_id: int
    chat_id: int
    first_name: str
    username: str | None
    language_code: str
    is_premium: bool
    bot: Bot | None = None
    settings: Settings | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class OpAdapter(Protocol):
    name: str

    async def check(self, user: OpContext) -> OpResult: ...

    async def verify(self, user: OpContext) -> OpResult: ...


def title_from_link(url: str, fallback: str) -> str:
    """``https://t.me/cryptonews?start=x`` → ``@cryptonews``; anything else → fallback."""
    for prefix in (
        "https://t.me/",
        "http://t.me/",
        "https://telegram.me/",
        "http://telegram.me/",
        "tg://resolve?domain=",
    ):
        if url.startswith(prefix):
            handle = url[len(prefix) :].split("?", 1)[0].split("/", 1)[0].strip()
            if handle.startswith("+") or handle in {"", "c", "joinchat", "addlist"}:
                return fallback
            return f"@{handle}"
    return fallback


class BoundedCache[K, V]:
    """Tiny LRU used by adapters to remember sponsor links per user."""

    def __init__(self, max_size: int = 10_000) -> None:
        self._max = max_size
        self._data: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K, default: V | None = None) -> V | None:
        value = self._data.get(key)
        if value is None:
            return default
        self._data.move_to_end(key)
        return value

    def set(self, key: K, value: V) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def pop(self, key: K) -> None:
        self._data.pop(key, None)

    def __len__(self) -> int:
        return len(self._data)
