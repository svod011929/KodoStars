"""v1.0: denormalized balance, admin roles, audit log, runtime settings,
broadcasts, payments, promo codes.

All changes are additive (ADD COLUMN / CREATE TABLE) so they apply to SQLite
without table rebuilds.

Revision ID: 0002_v1_admin_economy
Revises: 0001_baseline
Create Date: 2026-09-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_v1_admin_economy"
down_revision: str | None = "0001_baseline"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # --- users: denormalized balance + lifecycle markers -------------------------
    op.add_column(
        "users",
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("admin_note", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("blocked_bot_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_created_at", "users", ["created_at"])
    op.create_index("ix_users_last_action_at", "users", ["last_action_at"])
    # Backfill from the ledger (source of truth for legacy rows). Users that have
    # already pressed /start are marked as started so referral attribution stays closed.
    op.execute(
        "UPDATE users SET balance = ("
        "SELECT COALESCE(SUM(amount), 0) FROM ledger_entries "
        "WHERE ledger_entries.user_id = users.id)"
    )
    op.execute("UPDATE users SET started_at = created_at WHERE last_action_at IS NOT NULL")

    # --- payments -----------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("boost_products.id"), nullable=True),
        sa.Column("telegram_charge_id", sa.String(128), nullable=False, unique=True),
        sa.Column("provider_charge_id", sa.String(128), nullable=True),
        sa.Column("invoice_payload", sa.String(128), nullable=True),
        sa.Column("xtr_amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])

    # --- admins & audit ----------------------------------------------------------
    op.create_table(
        "admins",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_actions_admin_id", "admin_actions", ["admin_id"])
    op.create_index("ix_admin_actions_created", "admin_actions", ["created_at"])

    # --- runtime settings --------------------------------------------------------
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- broadcasts --------------------------------------------------------------
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("from_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("button_text", sa.String(64), nullable=True),
        sa.Column("button_url", sa.String(512), nullable=True),
        sa.Column("audience", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("sent", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("blocked", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- promo codes -------------------------------------------------------------
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("reward", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("promo_id", sa.Integer(), sa.ForeignKey("promo_codes.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("promo_id", "user_id", name="uq_promo_redemption"),
    )


def downgrade() -> None:
    for table in (
        "promo_redemptions",
        "promo_codes",
        "broadcasts",
        "app_settings",
        "admin_actions",
        "admins",
        "payments",
    ):
        op.drop_table(table)
    op.drop_index("ix_users_last_action_at", table_name="users")
    op.drop_index("ix_users_created_at", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("blocked_bot_at")
        batch.drop_column("started_at")
        batch.drop_column("admin_note")
        batch.drop_column("balance")
