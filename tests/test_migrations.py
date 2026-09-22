"""Alembic migrations must produce the same schema as the ORM models and must
upgrade a legacy (pre-Alembic) database in place."""

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, text

from app.config import Settings
from app.db.migrate import BASELINE_REVISION, alembic_config, run_migrations
from app.db.models import Base
from app.db.session import create_engine


def _schema(conn) -> dict[str, list[str]]:
    inspector = inspect(conn)
    return {
        table: sorted(column["name"] for column in inspector.get_columns(table))
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


def _indexes(conn) -> dict[str, set[str]]:
    inspector = inspect(conn)
    out: dict[str, set[str]] = {}
    for table in inspector.get_table_names():
        if table == "alembic_version":
            continue
        out[table] = {index["name"] for index in inspector.get_indexes(table) if index["name"]}
    return out


def _settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        admin_ids_raw="1",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / name).as_posix()}",
    )


@pytest.mark.asyncio
async def test_fresh_upgrade_matches_create_all(tmp_path: Path) -> None:
    migrated_settings = _settings(tmp_path, "migrated.db")
    engine = create_engine(migrated_settings)
    assert await run_migrations(engine, migrated_settings) == "fresh"
    async with engine.connect() as conn:
        migrated = await conn.run_sync(_schema)
        migrated_indexes = await conn.run_sync(_indexes)
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    await engine.dispose()

    created_settings = _settings(tmp_path, "created.db")
    engine = create_engine(created_settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.connect() as conn:
        created = await conn.run_sync(_schema)
        created_indexes = await conn.run_sync(_indexes)
    await engine.dispose()

    assert migrated == created
    assert migrated_indexes == created_indexes
    assert version == "0009_tgrass_unsubs"


@pytest.mark.asyncio
async def test_legacy_database_is_stamped_and_upgraded(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "legacy.db")
    engine = create_engine(settings)

    def _baseline(conn) -> None:
        cfg = alembic_config(settings)
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, BASELINE_REVISION)

    async with engine.begin() as conn:
        await conn.run_sync(_baseline)
        await conn.execute(text("DROP TABLE alembic_version"))
        await conn.execute(
            text(
                "INSERT INTO users (id, first_name, language_code, is_premium, is_banned, "
                "referral_activated, activity_score, xp, level, streak, last_action_at) "
                "VALUES (7, 'L', 'ru', 0, 0, 0, 3, 0, 1, 0, CURRENT_TIMESTAMP), "
                "(8, 'N', 'ru', 0, 0, 0, 0, 0, 1, 0, NULL)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO ledger_entries (user_id, amount, balance_after, kind) "
                "VALUES (7, 40, 40, 'task'), (7, -15, 25, 'withdraw_sent')"
            )
        )

    assert await run_migrations(engine, settings) == "legacy_stamped"
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT balance, started_at FROM users WHERE id = 7"))).one()
        never_started = (await conn.execute(text("SELECT balance, started_at FROM users WHERE id = 8"))).one()
        schema = await conn.run_sync(_schema)
    assert row[0] == 25
    assert row[1] is not None
    assert never_started[0] == 0 and never_started[1] is None
    assert "payments" in schema and "balance" in schema["users"]

    # Second start is a plain no-op upgrade.
    assert await run_migrations(engine, settings) == "upgrade"
    await engine.dispose()
