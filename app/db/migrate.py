"""Programmatic Alembic runner used on bot startup.

* Fresh database → ``upgrade head`` creates everything.
* Legacy database created by ``create_all`` (no ``alembic_version`` table but
  ``users`` exists) → stamped to the baseline revision first, then upgraded.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings

BASELINE_REVISION = "0001_baseline"
# app/db/migrate.py → app/migrations. Independent of alembic.ini so the package
# works both from a source checkout and when installed with pip.
_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

log = structlog.get_logger("kodostars.db")


def alembic_config(settings: Settings) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    cfg.attributes["configure_logging"] = False
    return cfg


def _run_sync(connection: Connection, settings: Settings) -> str:
    inspector = inspect(connection)
    has_version = inspector.has_table("alembic_version")
    has_users = inspector.has_table("users")
    cfg = alembic_config(settings)
    cfg.attributes["connection"] = connection
    mode = "fresh"
    if has_users and not has_version:
        mode = "legacy_stamped"
        command.stamp(cfg, BASELINE_REVISION)
    elif has_version:
        mode = "upgrade"
    command.upgrade(cfg, "head")
    return mode


async def run_migrations(engine: AsyncEngine, settings: Settings) -> str:
    """Bring the schema to ``head``. Returns the mode used (fresh/legacy_stamped/upgrade)."""
    async with engine.begin() as conn:
        mode = await conn.run_sync(_run_sync, settings)
    log.info("db_migrated", mode=mode)
    return mode
