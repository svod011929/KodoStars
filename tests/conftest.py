from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Base
from app.db.session import create_engine


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bot_token="000000000:PLACEHOLDER_TOKEN_REPLACE_ME",
        admin_ids_raw="1",
        database_url="sqlite+aiosqlite://",
        referral_levels=2,
        referral_l1_percent=15,
        referral_l2_percent=5,
        referral_l1_bonus=10,
        referral_l2_bonus=3,
        min_referral_activity=2,
        signup_bonus=0,
        claim_cooldown_seconds=0,
    )


@pytest.fixture
async def session(settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()
