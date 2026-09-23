"""Split OP traffic stats by provider.

Revision ID: 0012_op_provider_stats
Revises: 0011_drop_withdraw_fee
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_op_provider_stats"
down_revision: str | None = "0011_drop_withdraw_fee"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _provider_column() -> sa.Column:
    return sa.Column(
        "provider",
        sa.String(length=32),
        nullable=False,
        server_default=sa.text("'piarflow'"),
    )


def upgrade() -> None:
    with op.batch_alter_table("piarflow_issued_subs") as batch:
        batch.add_column(_provider_column())
        batch.drop_constraint("uq_piarflow_issued_sub", type_="unique")
        batch.create_unique_constraint("uq_piarflow_issued_sub", ["provider", "user_id", "offer_link"])
    with op.batch_alter_table("piarflow_paid_subs") as batch:
        batch.add_column(_provider_column())
        batch.drop_constraint("uq_piarflow_paid_sub", type_="unique")
        batch.create_unique_constraint("uq_piarflow_paid_sub", ["provider", "user_id", "offer_link"])


def downgrade() -> None:
    with op.batch_alter_table("piarflow_paid_subs") as batch:
        batch.drop_constraint("uq_piarflow_paid_sub", type_="unique")
        batch.create_unique_constraint("uq_piarflow_paid_sub", ["user_id", "offer_link"])
        batch.drop_column("provider")
    with op.batch_alter_table("piarflow_issued_subs") as batch:
        batch.drop_constraint("uq_piarflow_issued_sub", type_="unique")
        batch.create_unique_constraint("uq_piarflow_issued_sub", ["user_id", "offer_link"])
        batch.drop_column("provider")
