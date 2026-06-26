from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Founder Command Center"
    database_url: str = "sqlite:///./founder_command_center.db"
    secret_key: str = "change-this-in-production"
    access_token_expire_minutes: int = 720
    cors_origins: list[str] = ["http://localhost:5178", "http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
