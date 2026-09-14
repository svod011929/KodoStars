from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.db.models import User


@dataclass(slots=True)
class OpResult:
    passed: bool
    provider: str
    reason: str | None = None
    links: list[str] = field(default_factory=list)
    extra: dict[str, object] | None = None


class OpAdapter(ABC):
    name: str

    @abstractmethod
    async def check(self, user: User) -> OpResult:
        raise NotImplementedError

    async def verify(self, user: User) -> OpResult:
        return await self.check(user)
