"""Ambassador slots + promo day key on promo_codes.

Revision ID: 0008_ambassador_slots
Revises: 0007_piarflow_issued_subs
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_ambassador_slots"
down_revision: str | None = "0007_piarflow_issued_subs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ambassador_slots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("invite_link", sa.String(512), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("l1_bonus", sa.Integer(), nullable=True),
        sa.Column("l1_percent", sa.Integer(), nullable=True),
        sa.Column("l2_bonus", sa.Integer(), nullable=True),
        sa.Column("l2_percent", sa.Integer(), nullable=True),
        sa.Column("promo_reward", sa.Integer(), nullable=True),
        sa.Column("promo_max_uses", sa.Integer(), nullable=True),
        sa.Column("promo_auto_post", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ambassador_slots_user_id", "ambassador_slots", ["user_id"])
    op.create_index("ix_ambassador_slots_status", "ambassador_slots", ["status"])
    op.create_index("ix_ambassador_slots_user_status", "ambassador_slots", ["user_id", "status"])

    with op.batch_alter_table("promo_codes") as batch:
        batch.add_column(sa.Column("ambassador_slot_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("promo_day_key", sa.String(10), nullable=True))
        batch.create_foreign_key(
            "fk_promo_codes_ambassador_slot_id",
            "ambassador_slots",
            ["ambassador_slot_id"],
            ["id"],
        )
        batch.create_index("ix_promo_codes_ambassador_slot_id", ["ambassador_slot_id"])
        batch.create_unique_constraint("uq_ambassador_promo_day", ["ambassador_slot_id", "promo_day_key"])


def downgrade() -> None:
    with op.batch_alter_table("promo_codes") as batch:
        batch.drop_constraint("uq_ambassador_promo_day", type_="unique")
        batch.drop_index("ix_promo_codes_ambassador_slot_id")
        batch.drop_constraint("fk_promo_codes_ambassador_slot_id", type_="foreignkey")
        batch.drop_column("promo_day_key")
        batch.drop_column("ambassador_slot_id")
    op.drop_index("ix_ambassador_slots_user_status", table_name="ambassador_slots")
    op.drop_index("ix_ambassador_slots_status", table_name="ambassador_slots")
    op.drop_index("ix_ambassador_slots_user_id", table_name="ambassador_slots")
    op.drop_table("ambassador_slots")
