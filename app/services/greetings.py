"""Rotating welcome posts (приветки) shown once the user is inside the bot."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Greeting
from app.services.errors import ValidationError


async def list_greetings(session: AsyncSession) -> list[Greeting]:
    result = await session.execute(select(Greeting).order_by(Greeting.id.desc()))
    return list(result.scalars().all())


async def create_greeting(
    session: AsyncSession,
    *,
    body: str,
    button_text: str | None = None,
    button_url: str | None = None,
) -> Greeting:
    text = body.strip()
    if len(text) < 1 or len(text) > 3500:
        raise ValidationError("Текст приветки: от 1 до 3500 символов")
    label = (button_text or "").strip()
    url = (button_url or "").strip()
    if bool(label) != bool(url):
        raise ValidationError("Кнопка: и текст, и ссылка https://")
    if url and not url.startswith("https://"):
        raise ValidationError("Ссылка кнопки должна начинаться с https://")
    row = Greeting(
        body=text,
        button_text=label[:64] or None,
        button_url=url[:512] or None,
        is_active=True,
    )
    session.add(row)
    await session.flush()
    return row


async def toggle_greeting(session: AsyncSession, greeting_id: int) -> Greeting | None:
    row = await session.get(Greeting, greeting_id)
    if row is None:
        return None
    row.is_active = not row.is_active
    await session.flush()
    return row


async def delete_greeting(session: AsyncSession, greeting_id: int) -> bool:
    row = await session.get(Greeting, greeting_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def pick_greeting(session: AsyncSession) -> Greeting | None:
    """Least-shown active greeting, then bump its counter (round-robin)."""
    result = await session.execute(
        select(Greeting)
        .where(Greeting.is_active.is_(True))
        .order_by(Greeting.shows.asc(), Greeting.id.asc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.shows += 1
    await session.flush()
    return row
