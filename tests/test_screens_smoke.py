"""Every button reachable from the user and admin menus opens without an error,
and every screen is HTML that Telegram accepts (checked by the fake session)."""

from collections import deque

import pytest
import pytest_asyncio
from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Update

from app.bot.commands import ADMIN_COMMANDS
from app.db.models import LedgerKind
from app.services import ledger
from tests.conftest import ADMIN_ID, OTHER_ID, USER_ID, BotHarness
from tests.fake_telegram import callback_update, message_update

pytestmark = pytest.mark.asyncio(loop_scope="module")

ACTORS = (USER_ID, ADMIN_ID)
COMMANDS = [*(f"/{command.command}" for command in ADMIN_COMMANDS), "/terms"]
# Maintenance would hide the user's screens for the rest of the crawl.
SKIP = frozenset({"admin:set:maintenance_mode:on"})
CRASH = "Что-то пошло не так"


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def _clean_state(harness: BotHarness) -> None:
    await harness.reset()


def _buttons(requests: list[TelegramMethod]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for request in requests:
        markup = getattr(request, "reply_markup", None)
        chat_id = getattr(request, "chat_id", None)
        if not isinstance(markup, InlineKeyboardMarkup) or chat_id not in ACTORS:
            continue
        for row in markup.inline_keyboard:
            found += [(chat_id, button.callback_data) for button in row if button.callback_data]
    return found


@pytest.mark.asyncio
async def test_every_reachable_button_opens(harness: BotHarness) -> None:
    h = harness
    for actor in ACTORS:
        await h.feed(message_update(actor, "/start"))
    await h.feed(message_update(OTHER_ID, f"/start ref_{USER_ID}"))
    await h.feed(callback_update(ADMIN_ID, "admin:set:contest_enabled:on"))
    async with h.factory() as session:
        await ledger.credit(session, user_id=USER_ID, amount=1000, kind=LedgerKind.TASK)
        await session.commit()

    queue: deque[tuple[str, Update]] = deque(
        (command, message_update(actor, command)) for actor in ACTORS for command in COMMANDS
    )
    seen: set[tuple[int, str]] = set()
    crashes: list[str] = []
    while queue:
        label, update = queue.popleft()
        start = len(h.tg.requests)
        await h.feed(update)
        sent = h.tg.requests[start:]
        crashes += [label for request in sent if CRASH in (getattr(request, "text", None) or "")]
        for actor, data in _buttons(sent):
            if (actor, data) not in seen and data not in SKIP:
                seen.add((actor, data))
                queue.append((f"{actor} {data}", callback_update(actor, data)))

    assert crashes == []
    assert {"menu:top:contest", "wd:g:g50", "admin:wd:list:pending:0", "admin:set:g:engagement"} <= {
        data for _, data in seen
    }
