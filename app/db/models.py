from __future__ import annotations

from datetime import UTC, date, datetime
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
    WITHDRAW_HOLD = "withdraw_hold"
    WITHDRAW_FEE = "withdraw_fee"
    WITHDRAW_REFUND = "withdraw_refund"
    WITHDRAW_SENT = "withdraw_sent"
    ADMIN_ADJUST = "admin_adjust"
    PROMO = "promo"
    REFUND_REVOKE = "refund_revoke"
    UNSUB_PENALTY = "unsub_penalty"


LEDGER_KIND_LABELS: dict[str, str] = {
    LedgerKind.SIGNUP.value: "Бонус за регистрацию",
    LedgerKind.DAILY.value: "Ежедневная награда",
    LedgerKind.TASK.value: "Задание",
    LedgerKind.BOOST_PACK.value: "Покупка пака",
    LedgerKind.REFERRAL_BONUS.value: "Бонус за реферала",
    LedgerKind.REFERRAL_SHARE.value: "Доля с реферала",
    LedgerKind.WITHDRAW_HOLD.value: "Заявка на вывод",
    LedgerKind.WITHDRAW_FEE.value: "Комиссия за вывод",
    LedgerKind.WITHDRAW_REFUND.value: "Возврат по заявке",
    LedgerKind.WITHDRAW_SENT.value: "Выплата",
    LedgerKind.ADMIN_ADJUST.value: "Корректировка админа",
    LedgerKind.PROMO.value: "Промокод",
    LedgerKind.REFUND_REVOKE.value: "Возврат платежа",
    LedgerKind.UNSUB_PENALTY.value: "Штраф за отписку",
}


class WithdrawalStatus(StrEnum):
    PENDING = "pending"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    APPROVED_MANUAL = "approved_manual"
    SENT = "sent"


OPEN_WITHDRAWAL_STATUSES: tuple[str, ...] = (
    WithdrawalStatus.PENDING.value,
    WithdrawalStatus.APPROVED_MANUAL.value,
)

WITHDRAWAL_STATUS_LABELS: dict[str, str] = {
    WithdrawalStatus.PENDING.value: "ожидает",
    WithdrawalStatus.REJECTED.value: "отклонена",
    WithdrawalStatus.CANCELLED.value: "отменена",
    WithdrawalStatus.APPROVED_MANUAL.value: "согласована",
    WithdrawalStatus.SENT.value: "выплачена",
}


class BoostKind(StrEnum):
    MULTIPLIER = "multiplier"
    STARS_PACK = "stars_pack"


class TaskKind(StrEnum):
    SUBSCRIBE = "subscribe"
    INVITE = "invite"
    STREAK = "streak"
    CUSTOM = "custom"


TASK_KIND_LABELS: dict[str, str] = {
    TaskKind.SUBSCRIBE.value: "Подписка на канал",
    TaskKind.INVITE.value: "Пригласить друзей",
    TaskKind.STREAK.value: "Серия ежедневок",
    TaskKind.CUSTOM.value: "Перейти по ссылке",
}


class PaymentStatus(StrEnum):
    PAID = "paid"
    REFUNDED = "refunded"


class BroadcastStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BroadcastAudience(StrEnum):
    ALL = "all"
    ACTIVE_7D = "active_7d"
    ACTIVATED = "activated"


BROADCAST_AUDIENCE_LABELS: dict[str, str] = {
    BroadcastAudience.ALL.value: "Все пользователи",
    BroadcastAudience.ACTIVE_7D.value: "Активные за 7 дней",
    BroadcastAudience.ACTIVATED.value: "С активированной рефкой",
}


class AdminRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"


class AmbassadorKind(StrEnum):
    CHANNEL = "channel"
    CHAT = "chat"
    BOT = "bot"


class AmbassadorStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


AMBASSADOR_KIND_LABELS: dict[str, str] = {
    AmbassadorKind.CHANNEL.value: "Канал",
    AmbassadorKind.CHAT.value: "Чат",
    AmbassadorKind.BOT.value: "Бот",
}

AMBASSADOR_STATUS_LABELS: dict[str, str] = {
    AmbassadorStatus.PENDING.value: "На проверке",
    AmbassadorStatus.APPROVED.value: "Одобрен",
    AmbassadorStatus.REJECTED.value: "Отклонён",
    AmbassadorStatus.REVOKED.value: "Отозван",
}


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_created_at", "created_at"),
        Index("ix_users_last_action_at", "last_action_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    language_code: Mapped[str] = mapped_column(String(8), default="ru")
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    referred_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    referral_activated: Mapped[bool] = mapped_column(Boolean, default=False)
    activity_score: Mapped[int] = mapped_column(Integer, default=0)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_daily_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_withdraw_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_op_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_bot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Anti-multiaccount (device verification through the Mini App).
    device_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_fp: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    twink_of: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ledger_entries: Mapped[list[LedgerEntry]] = relationship(back_populates="user")
    withdrawals: Mapped[list[Withdrawal]] = relationship(back_populates="user")

    @property
    def is_twink(self) -> bool:
        """Flagged as a multi-account and not whitelisted by an admin."""
        return self.twink_of is not None and not self.is_trusted

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name or str(self.id)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyClaim(Base):
    __tablename__ = "daily_claims"
    __table_args__ = (UniqueConstraint("user_id", "claimed_on", name="uq_daily_claim"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    claimed_on: Mapped[date] = mapped_column(Date)
    streak: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    """Money record for every Telegram Stars purchase (entitlement lives in UserBoost)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("boost_products.id"), nullable=True)
    telegram_charge_id: Mapped[str] = mapped_column(String(128), unique=True)
    provider_charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    invoice_payload: Mapped[str | None] = mapped_column(String(128), nullable=True)
    xtr_amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=PaymentStatus.PAID.value)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    gift_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gift_emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=WithdrawalStatus.PENDING.value)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="withdrawals")

    @property
    def gift_label(self) -> str:
        if self.gift_emoji:
            return f"{self.gift_emoji} · {self.amount} ⭐"
        if self.gift_id:
            return f"🎁 · {self.amount} ⭐"
        return f"{self.amount} ⭐"


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PiarflowIssuedSub(Base):
    """Sponsors shown to a user, one row per OP provider + user + link."""

    __tablename__ = "piarflow_issued_subs"
    __table_args__ = (
        UniqueConstraint("provider", "user_id", "offer_link", name="uq_piarflow_issued_sub"),
        Index("ix_piarflow_issued_subs_last_shown", "last_shown_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    offer_link: Mapped[str] = mapped_column(String(512))
    provider: Mapped[str] = mapped_column(String(32), default="piarflow", server_default="piarflow")
    show_count: Mapped[int] = mapped_column(Integer, default=1)
    first_shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PiarflowPaidSub(Base):
    """Offer links a provider credited (PiarFlow ``subscribed`` / Tgrass ``subscribed``)."""

    __tablename__ = "piarflow_paid_subs"
    __table_args__ = (UniqueConstraint("provider", "user_id", "offer_link", name="uq_piarflow_paid_sub"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    offer_link: Mapped[str] = mapped_column(String(512))
    provider: Mapped[str] = mapped_column(String(32), default="piarflow", server_default="piarflow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PiarflowUnsub(Base):
    """Idempotent log of PiarFlow unsubscribe webhooks (one row per user+offer)."""

    __tablename__ = "piarflow_unsubs"
    __table_args__ = (UniqueConstraint("tg_user_id", "offer_link", name="uq_piarflow_unsub"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    offer_link: Mapped[str] = mapped_column(String(512))
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    penalty: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TgrassUnsub(Base):
    """Idempotent log of Tgrass unsubscribe webhooks (one row per user+offer)."""

    __tablename__ = "tgrass_unsubs"
    __table_args__ = (UniqueConstraint("tg_user_id", "offer_link", name="uq_tgrass_unsub"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    offer_link: Mapped[str] = mapped_column(String(512))
    penalty: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeviceCheck(Base):
    """One Mini App verification: who, from which device fingerprint and IP."""

    __tablename__ = "device_checks"
    __table_args__ = (Index("ix_device_checks_ip_created", "ip", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    fp_hash: Mapped[str] = mapped_column(String(64), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tg_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    matched_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Admin(Base):
    """Admins managed from the bot. Env ``ADMIN_IDS`` are owners and never stored here."""

    __tablename__ = "admins"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default=AdminRole.ADMIN.value)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminAction(Base):
    __tablename__ = "admin_actions"
    __table_args__ = (Index("ix_admin_actions_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(48))
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger)
    from_chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(Integer)
    button_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    button_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    audience: Mapped[str] = mapped_column(String(32), default=BroadcastAudience.ALL.value)
    status: Mapped[str] = mapped_column(String(16), default=BroadcastStatus.PENDING.value)
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AmbassadorSlot(Base):
    __tablename__ = "ambassador_slots"
    __table_args__ = (Index("ix_ambassador_slots_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(128))
    invite_link: Mapped[str] = mapped_column(String(512))
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=AmbassadorStatus.PENDING.value, index=True)
    l1_bonus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    l1_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    l2_bonus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    l2_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promo_reward: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promo_max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promo_auto_post: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PromoCode(Base):
    __tablename__ = "promo_codes"
    __table_args__ = (
        UniqueConstraint("ambassador_slot_id", "promo_day_key", name="uq_ambassador_promo_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    reward: Mapped[int] = mapped_column(Integer)
    max_uses: Mapped[int] = mapped_column(Integer, default=0)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ambassador_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ambassador_slots.id"), nullable=True, index=True
    )
    promo_day_key: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (UniqueConstraint("promo_id", "user_id", name="uq_promo_redemption"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promo_id: Mapped[int] = mapped_column(Integer, ForeignKey("promo_codes.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Greeting(Base):
    """Rotating welcome post shown after a user gets into the bot."""

    __tablename__ = "greetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(Text)
    button_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    button_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    shows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class Campaign(Base):
    """Traffic-buy link ``?start=c_CODE``."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class CampaignHit(Base):
    __tablename__ = "campaign_hits"
    __table_args__ = (Index("ix_campaign_hits_campaign_created", "campaign_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
