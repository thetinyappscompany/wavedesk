"""Environment-driven settings (non-negotiable #8: secrets from env only)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WD_", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:wavedesk_pg@localhost:5432/wavedesk"
    redis_url: str = "redis://localhost:6379/0"
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False  # True behind HTTPS in production
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
