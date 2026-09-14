from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    daily_base_reward: int = 5
    daily_streak_bonus: int = 1
    daily_streak_cap: int = 7

    withdraw_min: int = 50
    withdraw_cooldown_hours: int = 24
    signup_bonus: int = 5
    claim_cooldown_seconds: int = 3

    op_timeout_sec: float = 8.0
    op_cache_sec: int = 180

    flyer_enabled: bool = True
    flyer_api_key: str = ""
    flyer_api_url: str = "https://api.flyerservice.io"

    subgram_enabled: bool = True
    subgram_api_key: str = ""
    subgram_api_url: str = "https://api.subgram.ru"

    botohub_enabled: bool = True
    botohub_api_key: str = ""
    botohub_api_url: str = "https://botohub.me/api/v1"
    botohub_bot_id: str = ""

    piarflow_enabled: bool = True
    piarflow_api_key: str = ""
    piarflow_api_url: str = "https://piarflow.com/v1"
    piarflow_max_sponsors: int = 5

    tgrass_enabled: bool = True
    tgrass_api_key: str = ""
    tgrass_api_url: str = "https://api.tgrass.online/v1"
    tgrass_channels: str = ""

    manual_enabled: bool = True
    manual_op_channels: str = ""

    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("referral_levels")
    @classmethod
    def _levels_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("REFERRAL_LEVELS must be >= 1")
        return value

    @property
    def admin_ids(self) -> frozenset[int]:
        if not self.admin_ids_raw.strip():
            return frozenset()
        return frozenset(
            int(part.strip())
            for part in self.admin_ids_raw.split(",")
            if part.strip()
        )

    @property
    def is_placeholder_token(self) -> bool:
        token = self.bot_token.strip()
        return (
            not token
            or "PLACEHOLDER" in token.upper()
            or token.startswith("000000000:")
        )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def referral_percent(self, level: int) -> int:
        mapping = {1: self.referral_l1_percent, 2: self.referral_l2_percent}
        return mapping.get(level, 0)

    def referral_bonus(self, level: int) -> int:
        mapping = {1: self.referral_l1_bonus, 2: self.referral_l2_bonus}
        return mapping.get(level, 0)

    def parse_channel_list(self, raw: str) -> list[str]:
        return [part.strip() for part in raw.split(",") if part.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
