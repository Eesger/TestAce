from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Twitter / X
    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    twitter_access_token: str = ""
    twitter_refresh_token: str = ""
    twitter_token_expires_at: float = 0.0
    twitter_user_id: str = ""

    # Storage
    db_path: str = "./data/bookmarks.db"

    # Embeddings
    embed_model: str = "all-MiniLM-L6-v2"

    # Idea extraction (Claude API)
    anthropic_api_key: str = ""
    idea_model: str = "claude-haiku-4-5-20251001"  # fast + cheap for batch extraction

    # Scheduler
    sync_interval_minutes: int = 1440  # default: once per day
    sync_cron: str = ""               # if set, overrides interval (e.g. "0 8 * * *")

    # Logging
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
