"""Tgrass unsubscribe idempotency table.

Revision ID: 0009_tgrass_unsubs
Revises: 0008_ambassador_slots
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_tgrass_unsubs"
down_revision: str | None = "0008_ambassador_slots"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tgrass_unsubs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_link", sa.String(512), nullable=False),
        sa.Column("penalty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tg_user_id", "offer_link", name="uq_tgrass_unsub"),
    )
    op.create_index("ix_tgrass_unsubs_tg_user_id", "tgrass_unsubs", ["tg_user_id"])


def downgrade() -> None:
    op.drop_index("ix_tgrass_unsubs_tg_user_id", table_name="tgrass_unsubs")
    op.drop_table("tgrass_unsubs")
