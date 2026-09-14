from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

# (level, min_xp, multiplier in basis points; 100 = 1.00x)
LEVEL_TABLE: tuple[tuple[int, int, int], ...] = (
    (1, 0, 100),
    (2, 40, 105),
    (3, 120, 110),
    (4, 280, 115),
    (5, 520, 125),
    (6, 880, 135),
    (7, 1400, 150),
    (8, 2100, 165),
    (9, 3000, 180),
    (10, 4200, 200),
)


@dataclass(frozen=True, slots=True)
class LevelInfo:
    level: int
    min_xp: int
    multiplier_bp: int
    next_level: int | None
    next_xp: int | None


def info_for_xp(xp: int) -> LevelInfo:
    current = LEVEL_TABLE[0]
    for row in LEVEL_TABLE:
        if xp >= row[1]:
            current = row
        else:
            break
    nxt = next((row for row in LEVEL_TABLE if row[0] == current[0] + 1), None)
    return LevelInfo(
        level=current[0],
        min_xp=current[1],
        multiplier_bp=current[2],
        next_level=nxt[0] if nxt else None,
        next_xp=nxt[1] if nxt else None,
    )


def apply_multipliers(base: int, *multipliers_bp: int) -> int:
    amount = base
    for bp in multipliers_bp:
        if bp <= 0:
            continue
        amount = (amount * bp + 50) // 100
    return max(amount, 0)


async def add_xp(session: AsyncSession, user: User, xp: int) -> LevelInfo:
    user.xp += max(xp, 0)
    info = info_for_xp(user.xp)
    user.level = info.level
    await session.flush()
    return info
