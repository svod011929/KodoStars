"""Weekly referral contest: one row per ISO week, the winners it paid, and an index
for counting the friends activated within a week.

Revision ID: 0014_weekly_contest
Revises: 0013_daily_reminders
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_weekly_contest"
down_revision: str | None = "0013_daily_reminders"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("week_key", sa.String(10), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("prizes", sa.JSON(), nullable=True),
        sa.Column("min_referrals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("week_key", name="uq_contests_week_key"),
    )
    op.create_table(
        "contest_winners",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contest_id", sa.Integer(), sa.ForeignKey("contests.id"), nullable=False),
        sa.Column("place", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("prize", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("contest_id", "place", name="uq_contest_winner_place"),
    )
    op.create_index("ix_referral_level_credited", "referral_edges", ["level", "credited_at"])


def downgrade() -> None:
    op.drop_index("ix_referral_level_credited", table_name="referral_edges")
    op.drop_table("contest_winners")
    op.drop_table("contests")
