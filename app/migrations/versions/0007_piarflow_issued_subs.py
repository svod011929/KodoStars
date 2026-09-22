"""PiarFlow issued-sponsor inventory for traffic stats.

Revision ID: 0007_piarflow_issued_subs
Revises: 0006_piarflow_paid_subs
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_piarflow_issued_subs"
down_revision: str | None = "0006_piarflow_paid_subs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "piarflow_issued_subs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_link", sa.String(512), nullable=False),
        sa.Column("show_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_shown_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_shown_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "offer_link", name="uq_piarflow_issued_sub"),
    )
    op.create_index("ix_piarflow_issued_subs_user_id", "piarflow_issued_subs", ["user_id"])
    op.create_index("ix_piarflow_issued_subs_last_shown", "piarflow_issued_subs", ["last_shown_at"])


def downgrade() -> None:
    op.drop_index("ix_piarflow_issued_subs_last_shown", table_name="piarflow_issued_subs")
    op.drop_index("ix_piarflow_issued_subs_user_id", table_name="piarflow_issued_subs")
    op.drop_table("piarflow_issued_subs")
