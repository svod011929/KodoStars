"""Keep database transactions away from network I/O.

SQLite has a single writer. A handler that writes a row and then awaits a Telegram
API call or an OP-provider HTTP request holds the write lock for the whole round
trip, and every other user's update piles up behind it until ``busy_timeout``
expires with «database is locked». The rule is therefore:

    a transaction must never span network I/O.

``DbSessionMiddleware`` binds the per-update session to a context variable; every
outbound call (Telegram API via ``CommitBeforeRequestMiddleware``, OP cascade via
``OpGate.enforce``) calls :func:`commit_before_io` first. Work done so far is
committed (it is the source of truth anyway — a failed message can be retried),
the lock is released, and the handler continues in a fresh transaction.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger("kodostars.db")

_current_session: ContextVar[AsyncSession | None] = ContextVar("kodostars_session", default=None)


def bind_session(session: AsyncSession) -> Token[AsyncSession | None]:
    return _current_session.set(session)


def unbind_session(token: Token[AsyncSession | None]) -> None:
    _current_session.reset(token)


def current_session() -> AsyncSession | None:
    return _current_session.get()


async def commit_before_io() -> bool:
    """Commit the bound session if it has an open transaction. Returns True if it did."""
    session = _current_session.get()
    if session is None or not session.in_transaction():
        return False
    try:
        await session.commit()
    except Exception:
        # Leave the session in a clean state for the error handler; the caller sees
        # the original error through the exception chain.
        await session.rollback()
        raise
    return True
