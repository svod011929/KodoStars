from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from aiogram import Bot


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

    @classmethod
    def ok(cls, provider: str, message: str = "") -> OpResult:
        return cls(allowed=True, provider=provider, message=message)

    @classmethod
    def blocked(
        cls,
        provider: str,
        sponsors: list[Sponsor],
        message: str = "",
    ) -> OpResult:
        return cls(allowed=False, provider=provider, sponsors=sponsors, message=message)

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
    extra: dict[str, Any] = field(default_factory=dict)


class OpAdapter(Protocol):
    name: str

    async def check(self, user: OpContext) -> OpResult: ...

    async def verify(self, user: OpContext) -> OpResult: ...
