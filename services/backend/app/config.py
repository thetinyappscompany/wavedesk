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

    # Public origin of the SPA — used to build links we email out (password
    # resets). Must be the address a user's browser can reach.
    app_base_url: str = "http://localhost:5173"

    # Transactional email (Zoho SMTP by default). Unset host = email disabled:
    # nothing is sent and callers degrade gracefully. Secrets from env only.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # defaults to smtp_user when blank
    smtp_starttls: bool = True  # False = implicit TLS (port 465)


@lru_cache
def get_settings() -> Settings:
    return Settings()
