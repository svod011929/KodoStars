"""Daily-claim reminders: per-user opt-out and the last reminder date.

Revision ID: 0013_daily_reminders
Revises: 0012_op_provider_stats
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_daily_reminders"
down_revision: str | None = "0012_op_provider_stats"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("users", sa.Column("last_reminded_on", sa.Date(), nullable=True))
    op.create_index("ix_users_last_daily_on", "users", ["last_daily_on"])


def downgrade() -> None:
    op.drop_index("ix_users_last_daily_on", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_reminded_on")
        batch.drop_column("reminders_enabled")
