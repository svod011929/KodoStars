"""Store selected Telegram gift on withdrawal requests.

Revision ID: 0004_withdraw_gifts
Revises: 0003_device_checks
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_withdraw_gifts"
down_revision: str | None = "0003_device_checks"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("withdrawals", sa.Column("gift_id", sa.String(64), nullable=True))
    op.add_column("withdrawals", sa.Column("gift_emoji", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("withdrawals") as batch:
        batch.drop_column("gift_emoji")
        batch.drop_column("gift_id")
