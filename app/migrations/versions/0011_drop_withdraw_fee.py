"""Drop the withdrawal commission column.

Revision ID: 0011_drop_withdraw_fee
Revises: 0010_traffic_kit
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_drop_withdraw_fee"
down_revision: str | None = "0010_traffic_kit"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("withdrawals") as batch:
        batch.drop_column("fee")


def downgrade() -> None:
    op.add_column(
        "withdrawals",
        sa.Column("fee", sa.Integer(), nullable=False, server_default="0"),
    )
