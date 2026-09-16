from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminAction

ACTION_LABELS: dict[str, str] = {
    "withdrawal.approve": "Согласовал вывод",
    "withdrawal.reject": "Отклонил вывод",
    "withdrawal.sent": "Подтвердил выплату",
    "user.ban": "Бан",
    "user.unban": "Разбан",
    "user.adjust": "Корректировка баланса",
    "user.note": "Заметка о пользователе",
    "user.trust": "Доверие пользователю (антитвинк)",
    "user.message": "Сообщение пользователю",
    "provider.toggle": "Переключил ОП-провайдера",
    "settings.set": "Изменил настройку",
    "settings.reset": "Сбросил настройку",
    "broadcast.start": "Запустил рассылку",
    "broadcast.cancel": "Остановил рассылку",
    "task.create": "Создал задание",
    "task.update": "Изменил задание",
    "task.toggle": "Переключил задание",
    "task.delete": "Удалил задание",
    "boost.create": "Создал буст",
    "boost.update": "Изменил буст",
    "boost.toggle": "Переключил буст",
    "boost.delete": "Удалил буст",
    "promo.create": "Создал промокод",
    "promo.toggle": "Переключил промокод",
    "promo.delete": "Удалил промокод",
    "payment.refund": "Вернул платёж",
    "admin.add": "Добавил админа",
    "admin.remove": "Удалил админа",
    "users.import": "Импорт пользователей",
    "export": "Экспорт данных",
    "channel.add": "Добавил канал ОП",
    "channel.remove": "Удалил канал ОП",
}


async def log_action(
    session: AsyncSession,
    *,
    admin_id: int,
    action: str,
    target_type: str | None = None,
    target_id: int | str | None = None,
    **detail: Any,
) -> AdminAction:
    row = AdminAction(
        admin_id=admin_id,
        action=action[:48],
        target_type=target_type,
        target_id=str(target_id)[:64] if target_id is not None else None,
        detail=detail or None,
    )
    session.add(row)
    await session.flush()
    return row


async def recent(
    session: AsyncSession,
    *,
    limit: int = 15,
    offset: int = 0,
    admin_id: int | None = None,
) -> list[AdminAction]:
    stmt = select(AdminAction).order_by(AdminAction.id.desc()).offset(offset).limit(limit)
    if admin_id is not None:
        stmt = stmt.where(AdminAction.admin_id == admin_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(AdminAction))).scalar_one())


def label(action: str) -> str:
    return ACTION_LABELS.get(action, action)
