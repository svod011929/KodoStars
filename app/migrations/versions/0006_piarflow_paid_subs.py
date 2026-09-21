"""Track PiarFlow paid subscriptions for referral quality gating.

Revision ID: 0006_piarflow_paid_subs
Revises: 0005_piarflow_fragment
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_piarflow_paid_subs"
down_revision: str | None = "0005_piarflow_fragment"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "piarflow_paid_subs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_link", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "offer_link", name="uq_piarflow_paid_sub"),
    )
    op.create_index("ix_piarflow_paid_subs_user_id", "piarflow_paid_subs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_piarflow_paid_subs_user_id", table_name="piarflow_paid_subs")
    op.drop_table("piarflow_paid_subs")
