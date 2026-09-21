"""PiarFlow unsubscribe webhook processing + Fragment Stars payouts migration.

Revision ID: 0005_piarflow_fragment
Revises: 0004_withdraw_gifts
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_piarflow_fragment"
down_revision: str | None = "0004_withdraw_gifts"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "piarflow_unsubs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_link", sa.String(512), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("bot_id", sa.BigInteger(), nullable=True),
        sa.Column("penalty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tg_user_id", "offer_link", name="uq_piarflow_unsub"),
    )
    op.create_index("ix_piarflow_unsubs_tg_user_id", "piarflow_unsubs", ["tg_user_id"])


def downgrade() -> None:
    op.drop_index("ix_piarflow_unsubs_tg_user_id", table_name="piarflow_unsubs")
    op.drop_table("piarflow_unsubs")
