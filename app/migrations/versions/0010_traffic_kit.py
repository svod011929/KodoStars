"""Withdrawal fee, rotating greetings, traffic campaign hits.

Revision ID: 0010_traffic_kit
Revises: 0009_tgrass_unsubs
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_traffic_kit"
down_revision: str | None = "0009_tgrass_unsubs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "withdrawals",
        sa.Column("fee", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "greetings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("button_text", sa.String(64), nullable=True),
        sa.Column("button_url", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("shows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("title", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_campaigns_code"),
    )
    op.create_table(
        "campaign_hits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_campaign_hits_campaign_id", "campaign_hits", ["campaign_id"])
    op.create_index("ix_campaign_hits_user_id", "campaign_hits", ["user_id"])
    op.create_index(
        "ix_campaign_hits_campaign_created",
        "campaign_hits",
        ["campaign_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_hits_campaign_created", table_name="campaign_hits")
    op.drop_index("ix_campaign_hits_user_id", table_name="campaign_hits")
    op.drop_index("ix_campaign_hits_campaign_id", table_name="campaign_hits")
    op.drop_table("campaign_hits")
    op.drop_table("campaigns")
    op.drop_table("greetings")
    with op.batch_alter_table("withdrawals") as batch:
        batch.drop_column("fee")
