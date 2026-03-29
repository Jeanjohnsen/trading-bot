from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.models import AppMode


ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "config"
STORAGE_DIR = ROOT_DIR / "storage"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="POLY-ARB AGENT", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_mode: AppMode = Field(default=AppMode.PAPER, alias="APP_MODE")
    app_base_url: str = Field(default="http://127.0.0.1:8000", alias="APP_BASE_URL")

    database_url: str = Field(default="sqlite:///./storage/poly_arb_agent.db", alias="DATABASE_URL")

    bootstrap_demo_data: bool = Field(default=True, alias="BOOTSTRAP_DEMO_DATA")
    enable_research_mode: bool = Field(default=False, alias="ENABLE_RESEARCH_MODE")
    enable_live_trading: bool = Field(default=False, alias="ENABLE_LIVE_TRADING")
    enable_market_orders: bool = Field(default=False, alias="ENABLE_MARKET_ORDERS")

    polymarket_gamma_url: str = Field(default="https://gamma-api.polymarket.com", alias="POLYMARKET_GAMMA_URL")
    polymarket_clob_url: str = Field(default="https://clob.polymarket.com", alias="POLYMARKET_CLOB_URL")
    polymarket_relayer_api_key: str = Field(default="", alias="POLYMARKET_RELAYER_API_KEY")
    polymarket_relayer_api_key_address: str = Field(default="", alias="POLYMARKET_RELAYER_API_KEY_ADDRESS")

    anthropic_api_url: str = Field(default="https://api.anthropic.com/v1/messages", alias="ANTHROPIC_API_URL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514", alias="ANTHROPIC_MODEL")
    anthropic_version: str = Field(default="2023-06-01", alias="ANTHROPIC_VERSION")
    anthropic_max_tokens: int = Field(default=900, alias="ANTHROPIC_MAX_TOKENS")

    webhook_url: str = Field(default="", alias="WEBHOOK_URL")
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    def merged_runtime_config(self) -> dict[str, Any]:
        base_cfg = _read_yaml(CONFIG_DIR / "environments" / "base.yaml")
        env_cfg = _read_yaml(CONFIG_DIR / "environments" / f"{self.app_mode.value}.yaml")
        merged = _deep_merge(base_cfg, env_cfg)
        merged.setdefault("app", {})
        merged["app"].update(
            {
                "name": self.app_name,
                "env": self.app_env,
                "mode": self.app_mode.value,
                "base_url": self.app_base_url,
                "bootstrap_demo_data": self.bootstrap_demo_data,
                "enable_research_mode": self.enable_research_mode,
                "enable_live_trading": self.enable_live_trading,
                "enable_market_orders": self.enable_market_orders,
            }
        )
        return merged

    def storage_path(self, *parts: str) -> Path:
        path = STORAGE_DIR.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return settings

