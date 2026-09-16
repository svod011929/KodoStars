"""Admin roles: env owners (immutable) + DB-managed admins."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Admin, AdminRole
from app.services.errors import AccessDenied, NotFound, ValidationError


class AccessRegistry:
    """In-memory view of who is admin; the bot runs as a single process so the
    cache is authoritative and updated in place on every change."""

    def __init__(self, owner_ids: frozenset[int]) -> None:
        self._owners = frozenset(owner_ids)
        self._admins: set[int] = set()
        self._loaded = False

    @property
    def owners(self) -> frozenset[int]:
        return self._owners

    @property
    def loaded(self) -> bool:
        return self._loaded

    async def load(self, session: AsyncSession) -> None:
        result = await session.execute(select(Admin.user_id))
        self._admins = {int(uid) for uid in result.scalars().all()}
        self._loaded = True

    def is_owner(self, user_id: int) -> bool:
        return user_id in self._owners

    def is_admin(self, user_id: int) -> bool:
        return user_id in self._owners or user_id in self._admins

    def role(self, user_id: int) -> AdminRole | None:
        if user_id in self._owners:
            return AdminRole.OWNER
        if user_id in self._admins:
            return AdminRole.ADMIN
        return None

    def all_admin_ids(self) -> frozenset[int]:
        return frozenset(self._owners | self._admins)

    async def list_admins(self, session: AsyncSession) -> list[Admin]:
        result = await session.execute(select(Admin).order_by(Admin.created_at))
        return list(result.scalars().all())

    async def add_admin(self, session: AsyncSession, *, user_id: int, actor_id: int) -> Admin:
        if not self.is_owner(actor_id):
            raise AccessDenied("Добавлять админов могут только владельцы (ADMIN_IDS)")
        if user_id in self._owners:
            raise ValidationError("Этот пользователь уже владелец")
        existing = await session.get(Admin, user_id)
        if existing is not None:
            raise ValidationError("Этот пользователь уже админ")
        row = Admin(user_id=user_id, role=AdminRole.ADMIN.value, added_by=actor_id)
        session.add(row)
        await session.flush()
        self._admins.add(user_id)
        return row

    async def remove_admin(self, session: AsyncSession, *, user_id: int, actor_id: int) -> None:
        if not self.is_owner(actor_id):
            raise AccessDenied("Удалять админов могут только владельцы (ADMIN_IDS)")
        if user_id in self._owners:
            raise ValidationError("Владельца из ADMIN_IDS нельзя удалить через бота")
        row = await session.get(Admin, user_id)
        if row is None:
            raise NotFound("Такого админа нет")
        await session.delete(row)
        await session.flush()
        self._admins.discard(user_id)
