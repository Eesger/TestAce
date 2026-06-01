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

    # Scheduler
    sync_interval_minutes: int = 60

    # Logging
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
