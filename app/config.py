from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Keys that admins may override at runtime through the ``app_settings`` table.
# Everything else is env-only (tokens, DB URL, provider credentials, Fragment secrets).
RUNTIME_OVERRIDABLE: dict[str, type] = {
    "referral_l1_percent": int,
    "referral_l2_percent": int,
    "referral_l1_bonus": int,
    "referral_l2_bonus": int,
    "min_referral_activity": int,
    "referral_min_piarflow_subs": int,
    "daily_base_reward": int,
    "daily_streak_bonus": int,
    "daily_streak_cap": int,
    "withdraw_min": int,
    "withdraw_max": int,
    "withdraw_cooldown_hours": int,
    "withdraw_min_referrals": int,
    "withdraw_enabled": bool,
    "signup_bonus": int,
    "claim_cooldown_seconds": int,
    "op_cache_sec": int,
    "support_contact": str,
    "maintenance_mode": bool,
    "maintenance_text": str,
    "broadcast_rate_per_sec": int,
    "notify_referrer": bool,
    "device_check_enabled": bool,
    "device_check_for_withdraw": bool,
    "device_check_for_op": bool,
    "twink_block_referral": bool,
    "twink_block_withdraw": bool,
    "twink_block_op": bool,
    "twink_require_ip_match": bool,
    "twink_ip_window_days": int,
    "piarflow_unsub_penalty": int,
}

RUNTIME_SETTING_LABELS: dict[str, str] = {
    "referral_l1_percent": "Реф. доля L1, %",
    "referral_l2_percent": "Реф. доля L2, %",
    "referral_l1_bonus": "Бонус за активацию L1, ⭐",
    "referral_l2_bonus": "Бонус за активацию L2, ⭐",
    "min_referral_activity": "Порог активности реферала",
    "referral_min_piarflow_subs": "Реф. бонус: мин. оплаченных подписок PiarFlow",
    "daily_base_reward": "Ежедневка: база, ⭐",
    "daily_streak_bonus": "Ежедневка: бонус за день серии, ⭐",
    "daily_streak_cap": "Ежедневка: потолок серии",
    "withdraw_min": "Вывод: минимум, ⭐",
    "withdraw_max": "Вывод: максимум, ⭐ (0 = без лимита)",
    "withdraw_cooldown_hours": "Вывод: кулдаун, ч",
    "withdraw_min_referrals": "Вывод: мин. активных рефералов",
    "withdraw_enabled": "Вывод включён",
    "signup_bonus": "Бонус за регистрацию, ⭐",
    "claim_cooldown_seconds": "Антиспам: пауза между действиями, с",
    "op_cache_sec": "ОП: кэш проверки, с",
    "support_contact": "Контакт поддержки (@username)",
    "maintenance_mode": "Режим обслуживания",
    "maintenance_text": "Текст режима обслуживания",
    "broadcast_rate_per_sec": "Рассылка: сообщений в секунду",
    "notify_referrer": "Уведомлять реферера о новых рефералах",
    "device_check_enabled": "Антитвинк: проверка устройства (Mini App)",
    "device_check_for_withdraw": "Антитвинк: вывод только после проверки",
    "device_check_for_op": "Антитвинк: ОП только после проверки устройства",
    "twink_block_referral": "Антитвинк: не платить за реферала-твинка",
    "twink_block_withdraw": "Антитвинк: запрет вывода твинкам",
    "twink_block_op": "Антитвинк: не выдавать ОП твинкам",
    "twink_require_ip_match": "Антитвинк: считать твинком только при совпадении IP",
    "twink_ip_window_days": "Антитвинк: окно совпадения IP, дней",
    "piarflow_unsub_penalty": "PiarFlow: штраф за отписку, ⭐",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    bot_token: str = "000000000:PLACEHOLDER_TOKEN_REPLACE_ME"
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")

    database_url: str = "sqlite+aiosqlite:///./data/kodostars.db"

    referral_levels: int = 2
    referral_l1_percent: int = 15
    referral_l2_percent: int = 5
    referral_l1_bonus: int = 10
    referral_l2_bonus: int = 3
    min_referral_activity: int = 2
    referral_min_piarflow_subs: int = 2
    notify_referrer: bool = True

    daily_base_reward: int = 5
    daily_streak_bonus: int = 1
    daily_streak_cap: int = 7

    withdraw_min: int = 50
    withdraw_max: int = 0
    withdraw_cooldown_hours: int = 24
    withdraw_min_referrals: int = 0
    withdraw_enabled: bool = True
    signup_bonus: int = 5
    claim_cooldown_seconds: int = 3

    # Web server (Telegram Mini App + PiarFlow unsubscribe webhook).
    web_public_url: str = ""
    server_port: int = 8080
    web_host: str = "0.0.0.0"
    device_check_enabled: bool = True
    device_check_for_withdraw: bool = True
    device_check_for_op: bool = True
    twink_block_referral: bool = True
    twink_block_withdraw: bool = False
    twink_block_op: bool = True
    twink_require_ip_match: bool = False
    twink_ip_window_days: int = 30

    support_contact: str = ""
    maintenance_mode: bool = False
    maintenance_text: str = "Бот на техническом обслуживании. Загляните чуть позже."
    broadcast_rate_per_sec: int = 20
    throttle_seconds: float = 0.4

    op_timeout_sec: float = 8.0
    op_cache_sec: int = 180

    # PiarFlow — https://piarflow.com/api-docs (POST /sponsors, /sponsors/check, Bearer)
    piarflow_enabled: bool = True
    piarflow_api_key: str = ""
    piarflow_api_url: str = "https://piarflow.com/v1"
    piarflow_max_sponsors: int = 5
    piarflow_unsub_penalty: int = 10

    # Fragment — Stars payouts. Keep mnemonic/cookies ONLY in server .env.
    fragment_wallet_mnemonic: str = ""
    fragment_cookies: str = ""
    fragment_tonapi_key: str = ""
    fragment_wallet_version: str = "V5R1"
    fragment_show_sender: bool = False

    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("referral_levels")
    @classmethod
    def _levels_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("REFERRAL_LEVELS must be >= 1")
        return value

    @field_validator("referral_l1_percent", "referral_l2_percent")
    @classmethod
    def _percent_range(cls, value: int) -> int:
        if not 0 <= value <= 100:
            raise ValueError("referral percent must be within 0..100")
        return value

    @field_validator(
        "referral_l1_bonus",
        "referral_l2_bonus",
        "min_referral_activity",
        "referral_min_piarflow_subs",
        "daily_base_reward",
        "daily_streak_bonus",
        "daily_streak_cap",
        "withdraw_min",
        "withdraw_max",
        "withdraw_cooldown_hours",
        "withdraw_min_referrals",
        "signup_bonus",
        "claim_cooldown_seconds",
        "op_cache_sec",
        "piarflow_unsub_penalty",
    )
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be >= 0")
        return value

    @field_validator("broadcast_rate_per_sec")
    @classmethod
    def _rate_range(cls, value: int) -> int:
        if not 1 <= value <= 30:
            raise ValueError("BROADCAST_RATE_PER_SEC must be within 1..30 (Telegram limit)")
        return value

    @field_validator("fragment_wallet_version")
    @classmethod
    def _wallet_version(cls, value: str) -> str:
        normalized = value.strip().upper() or "V5R1"
        if normalized not in {"V4R2", "V5R1"}:
            raise ValueError("FRAGMENT_WALLET_VERSION must be V4R2 or V5R1")
        return normalized

    @model_validator(mode="after")
    def _withdraw_bounds(self) -> "Settings":
        if self.withdraw_max and self.withdraw_max < self.withdraw_min:
            raise ValueError("WITHDRAW_MAX must be 0 or >= WITHDRAW_MIN")
        return self

    @property
    def admin_ids(self) -> frozenset[int]:
        if not self.admin_ids_raw.strip():
            return frozenset()
        return frozenset(
            int(part.strip()) for part in self.admin_ids_raw.split(",") if part.strip().lstrip("-").isdigit()
        )

    @property
    def is_placeholder_token(self) -> bool:
        token = self.bot_token.strip()
        return not token or "PLACEHOLDER" in token.upper() or token.startswith("000000000:")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def web_enabled(self) -> bool:
        return self.web_public_url.strip().startswith("https://")

    @property
    def device_check_active(self) -> bool:
        """Device verification needs both the HTTPS Mini App URL and the runtime flag."""
        return self.web_enabled and self.device_check_enabled

    @property
    def fragment_configured(self) -> bool:
        return bool(
            self.fragment_wallet_mnemonic.strip()
            and self.fragment_cookies.strip()
            and self.fragment_tonapi_key.strip()
        )

    def web_url(self, path: str = "") -> str:
        return f"{self.web_public_url.strip().rstrip('/')}/{path.lstrip('/')}"

    def referral_percent(self, level: int) -> int:
        mapping = {1: self.referral_l1_percent, 2: self.referral_l2_percent}
        return mapping.get(level, 0)

    def referral_bonus(self, level: int) -> int:
        mapping = {1: self.referral_l1_bonus, 2: self.referral_l2_bonus}
        return mapping.get(level, 0)

    def parse_channel_list(self, raw: str) -> list[str]:
        return [part.strip() for part in raw.split(",") if part.strip()]

    def with_overrides(self, overrides: dict[str, Any]) -> "Settings":
        """Return a copy with runtime overrides applied (whitelisted keys only)."""
        clean = {k: v for k, v in overrides.items() if k in RUNTIME_OVERRIDABLE}
        if not clean:
            return self
        return self.model_copy(update=clean)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
