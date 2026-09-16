"""In-session domain events.

Services append events to ``session.info`` while they work; the DB middleware
drains them *after* a successful commit and hands them to ``app.bot.notify``.
This keeps Telegram I/O out of the services and guarantees that users are only
notified about state that actually persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

_KEY = "kodostars.events"


@dataclass(slots=True)
class DomainEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


def emit(session: AsyncSession, name: str, **payload: Any) -> None:
    session.info.setdefault(_KEY, []).append(DomainEvent(name=name, payload=payload))


def drain(session: AsyncSession) -> list[DomainEvent]:
    events: list[DomainEvent] = session.info.pop(_KEY, [])
    return events


def peek(session: AsyncSession) -> list[DomainEvent]:
    return list(session.info.get(_KEY, []))
