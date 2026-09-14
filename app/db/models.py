from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LedgerKind(StrEnum):
    SIGNUP = "signup"
    DAILY = "daily"
    TASK = "task"
    BOOST_PACK = "boost_pack"
    REFERRAL_BONUS = "referral_bonus"
    REFERRAL_SHARE = "referral_share"
    WITHDRAW_SENT = "withdraw_sent"
    ADMIN_ADJUST = "admin_adjust"


class WithdrawalStatus(StrEnum):
    PENDING = "pending"
    REJECTED = "rejected"
    APPROVED_MANUAL = "approved_manual"
    SENT = "sent"


class BoostKind(StrEnum):
    MULTIPLIER = "multiplier"
    STARS_PACK = "stars_pack"


class TaskKind(StrEnum):
    SUBSCRIBE = "subscribe"
    INVITE = "invite"
    STREAK = "streak"
    CUSTOM = "custom"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    language_code: Mapped[str] = mapped_column(String(8), default="ru")
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    referred_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    referral_activated: Mapped[bool] = mapped_column(Boolean, default=False)
    activity_score: Mapped[int] = mapped_column(Integer, default=0)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    last_daily_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_withdraw_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_op_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ledger_entries: Mapped[list[LedgerEntry]] = relationship(back_populates="user")
    withdrawals: Mapped[list[Withdrawal]] = relationship(back_populates="user")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index("ix_ledger_user_created", "user_id", "created_at"),
        Index("ix_ledger_kind_ref", "kind", "reference"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="ledger_entries")


class ReferralEdge(Base):
    __tablename__ = "referral_edges"
    __table_args__ = (
        UniqueConstraint("referrer_id", "referee_id", "level", name="uq_referral_edge"),
        Index("ix_referral_referrer", "referrer_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    referee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    level: Mapped[int] = mapped_column(Integer)
    credited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DailyClaim(Base):
    __tablename__ = "daily_claims"
    __table_args__ = (UniqueConstraint("user_id", "claimed_on", name="uq_daily_claim"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    claimed_on: Mapped[date] = mapped_column(Date)
    streak: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32))
    reward: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class UserTask(Base):
    __tablename__ = "user_tasks"
    __table_args__ = (UniqueConstraint("user_id", "task_id", name="uq_user_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id"))
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BoostProduct(Base):
    __tablename__ = "boost_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    xtr_price: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    multiplier_bp: Mapped[int] = mapped_column(Integer, default=100)
    duration_hours: Mapped[int] = mapped_column(Integer, default=0)
    stars_amount: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserBoost(Base):
    __tablename__ = "user_boosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("boost_products.id"))
    multiplier_bp: Mapped[int] = mapped_column(Integer, default=100)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default=WithdrawalStatus.PENDING.value)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="withdrawals")


class ProviderState(Base):
    __tablename__ = "provider_states"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FraudEvent(Base):
    __tablename__ = "fraud_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
