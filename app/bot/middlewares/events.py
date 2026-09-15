from aiogram.types import TelegramObject, Update
from aiogram.types.update import UpdateTypeLookupError


def unwrap_event(event: TelegramObject) -> TelegramObject:
    """Return the inner Telegram event when *event* is an ``Update``."""
    if isinstance(event, Update):
        try:
            return event.event
        except UpdateTypeLookupError:
            return event
    return event
