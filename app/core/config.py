"""
Central configuration for the Personal AI Agent.

Every other module reads config THROUGH this object — never via
os.getenv() directly. This keeps all environment/secret access
auditable from a single file.

Usage elsewhere:
    from app.core.config import settings
    settings.gemini_api_key
"""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigError

# Project root = two levels up from this file (app/core/config.py -> D:\Agent)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """
    Typed, validated application settings loaded from .env.

    Any required value that's missing will raise a validation error
    at import time — fail fast, not deep inside some tool call later.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore unrelated env vars rather than erroring
    )

    # --- LLM Providers ---
    gemini_api_key: str = Field(default="")
    groq_api_key: str = Field(default="")

    # --- Telegram ---
    telegram_bot_token: str = Field(default="")
    telegram_allowed_user_id: str = Field(default="")

    # --- App behavior ---
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # --- Paths (relative to project root, resolved to absolute below) ---
    data_dir: str = Field(default="data")
    logs_dir: str = Field(default="logs")
    db_path: str = Field(default="data/agent.db")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid:
            raise ConfigError(f"LOG_LEVEL must be one of {valid}, got: {v}")
        return v_upper

    @property
    def data_dir_path(self) -> Path:
        return PROJECT_ROOT / self.data_dir

    @property
    def logs_dir_path(self) -> Path:
        return PROJECT_ROOT / self.logs_dir

    @property
    def db_path_resolved(self) -> Path:
        return PROJECT_ROOT / self.db_path


def _validate_critical_settings(s: Settings) -> None:
    """
    Soft validation: warn-worthy conditions that shouldn't crash import
    (e.g. keys not filled in yet during early scaffolding) but WILL matter
    once we reach the milestone that actually uses them.

    Hard-required checks get added here as each milestone starts depending
    on a given key (e.g. gemini_api_key becomes required at M14).
    """
    if not s.data_dir_path.exists():
        raise ConfigError(f"data_dir does not exist: {s.data_dir_path}")
    if not s.logs_dir_path.exists():
        raise ConfigError(f"logs_dir does not exist: {s.logs_dir_path}")


# Singleton instance imported everywhere else
settings = Settings()
_validate_critical_settings(settings)