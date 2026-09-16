"""Anti-multiaccount: device verification through the Telegram Mini App.

Revision ID: 0003_device_checks
Revises: 0002_v1_admin_economy
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_device_checks"
down_revision: str | None = "0002_v1_admin_economy"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("device_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("device_fp", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("twink_of", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("is_trusted", sa.Boolean(), nullable=False, server_default="0"))
    op.create_index("ix_users_device_fp", "users", ["device_fp"])
    op.create_index("ix_users_twink_of", "users", ["twink_of"])

    op.create_table(
        "device_checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fp_hash", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("tg_version", sa.String(16), nullable=True),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column("matched_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_device_checks_user_id", "device_checks", ["user_id"])
    op.create_index("ix_device_checks_fp_hash", "device_checks", ["fp_hash"])
    op.create_index("ix_device_checks_ip_created", "device_checks", ["ip", "created_at"])


def downgrade() -> None:
    op.drop_table("device_checks")
    op.drop_index("ix_users_twink_of", table_name="users")
    op.drop_index("ix_users_device_fp", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_trusted")
        batch.drop_column("twink_of")
        batch.drop_column("device_fp")
        batch.drop_column("device_verified_at")
