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

XP_DAILY = 10
XP_TASK = 12
XP_BOOST = 15
XP_REFERRAL_L1 = 8
XP_REFERRAL_L2 = 3


@dataclass(frozen=True, slots=True)
class LevelInfo:
    level: int
    min_xp: int
    multiplier_bp: int
    next_level: int | None
    next_xp: int | None

    def progress(self, xp: int) -> float:
        """0.0..1.0 progress towards the next level (1.0 at max level)."""
        if self.next_xp is None:
            return 1.0
        span = max(self.next_xp - self.min_xp, 1)
        return min(max((xp - self.min_xp) / span, 0.0), 1.0)


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


def format_multiplier(bp: int) -> str:
    text = f"{bp / 100:.2f}".rstrip("0").rstrip(".")
    return f"×{text}"


def progress_bar(ratio: float, width: int = 10) -> str:
    filled = round(min(max(ratio, 0.0), 1.0) * width)
    return "▰" * filled + "▱" * (width - filled)


async def add_xp(session: AsyncSession, user: User, xp: int) -> LevelInfo:
    user.xp += max(xp, 0)
    info = info_for_xp(user.xp)
    user.level = info.level
    await session.flush()
    return info
