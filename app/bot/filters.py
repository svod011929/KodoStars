from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.services.access import AccessRegistry


class IsAdmin(BaseFilter):
    """Passes when the sender is an owner (env) or a DB-managed admin."""

    async def __call__(self, event: TelegramObject, access: AccessRegistry) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and access.is_admin(user.id)


class IsOwner(BaseFilter):
    async def __call__(self, event: TelegramObject, access: AccessRegistry) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and access.is_owner(user.id)
