from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BoostKind, BoostProduct, ProviderState, Task, TaskKind

PROVIDER_NAMES = ("flyer", "subgram", "botohub", "piarflow", "tgrass", "manual")

DEFAULT_TASKS = (
    {
        "slug": "invite_one",
        "title": "Приведи друга",
        "description": "Один реферал должен пройти антифрод-активацию.",
        "kind": TaskKind.INVITE.value,
        "reward": 15,
        "payload": {"invites": 1},
        "sort_order": 10,
    },
    {
        "slug": "streak_three",
        "title": "Серия 3 дня",
        "description": "Забери ежедневную награду три дня подряд.",
        "kind": TaskKind.STREAK.value,
        "reward": 20,
        "payload": {"streak": 3},
        "sort_order": 20,
    },
    {
        "slug": "first_boost",
        "title": "Первый буст",
        "description": "Купи любой буст за Telegram Stars.",
        "kind": TaskKind.CUSTOM.value,
        "reward": 10,
        "payload": {"event": "boost_purchased"},
        "sort_order": 30,
    },
)

DEFAULT_BOOSTS = (
    {
        "slug": "pack_25",
        "title": "Пак 25 ⭐",
        "description": "25 внутренних Stars на баланс.",
        "xtr_price": 15,
        "kind": BoostKind.STARS_PACK.value,
        "multiplier_bp": 100,
        "duration_hours": 0,
        "stars_amount": 25,
    },
    {
        "slug": "x2_24h",
        "title": "×2 на 24 часа",
        "description": "Удваивает награды за ежедневку, задания и реф. долю.",
        "xtr_price": 25,
        "kind": BoostKind.MULTIPLIER.value,
        "multiplier_bp": 200,
        "duration_hours": 24,
        "stars_amount": 0,
    },
    {
        "slug": "x3_12h",
        "title": "×3 на 12 часов",
        "description": "Тройной множитель на полдня.",
        "xtr_price": 40,
        "kind": BoostKind.MULTIPLIER.value,
        "multiplier_bp": 300,
        "duration_hours": 12,
        "stars_amount": 0,
    },
)


async def seed_catalog(session: AsyncSession) -> None:
    existing_tasks = {row.slug for row in (await session.execute(select(Task))).scalars()}
    for item in DEFAULT_TASKS:
        if item["slug"] not in existing_tasks:
            session.add(Task(**item, is_active=True))

    existing_boosts = {
        row.slug for row in (await session.execute(select(BoostProduct))).scalars()
    }
    for item in DEFAULT_BOOSTS:
        if item["slug"] not in existing_boosts:
            session.add(BoostProduct(**item, is_active=True))

    existing_providers = {
        row.name for row in (await session.execute(select(ProviderState))).scalars()
    }
    for name in PROVIDER_NAMES:
        if name not in existing_providers:
            session.add(ProviderState(name=name, enabled=True))

    await session.commit()
