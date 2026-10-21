"""
Application settings loaded from environment variables / .env file.

Interview note:
- Centralizing config via pydantic-settings makes the app 12-factor friendly
  (config via env) and keeps secrets out of source control.
- On AWS: inject these via EC2 user-data, SSM Parameter Store, or Secrets Manager
  rather than baking .env into the AMI.
"""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Appointment Booking System"
    app_env: str = "development"
    debug: bool = True

    database_url: str = "postgresql://booking_user:booking_pass@localhost:5432/appointment_db"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "change-me-to-a-long-random-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    redis_lock_ttl_seconds: int = 10
    booking_rate_limit_per_minute: int = 5

    reminder_job_interval_minutes: int = 15
    reminder_lookahead_hours: int = 24

    # Stored as comma-separated string in .env; parsed to list
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # Render / Heroku often give postgres:// — SQLAlchemy needs postgresql://
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    @field_validator("jwt_secret_key")
    @classmethod
    def warn_weak_secret(cls, v: str) -> str:
        if v == "change-me-to-a-long-random-secret-in-production":
            # Soft warning only — don't crash local demos
            import warnings

            warnings.warn(
                "JWT_SECRET_KEY is using the default value. "
                "Generate a strong secret before deploying.",
                UserWarning,
                stacklevel=2,
            )
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — one parse of env per process."""
    return Settings()
