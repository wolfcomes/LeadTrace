from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration with stricter production invariants."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LEADTRACE_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = (
        "postgresql+psycopg://leadtrace:leadtrace-development-only@postgres/leadtrace"
    )
    redis_url: str = "redis://redis:6379/0"
    session_secret: SecretStr = SecretStr("development-only-not-for-production")
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    asset_root: Path = Path("/var/lib/leadtrace/assets")

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.environment != "production":
            return self

        database_url = self.database_url.strip()
        if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("production database_url must use PostgreSQL")
        if any(
            marker in database_url.casefold()
            for marker in (":password@", ":change-me@", ":leadtrace-development-only@")
        ):
            raise ValueError("production database_url contains placeholder credentials")

        secret = self.session_secret.get_secret_value()
        unsafe_secret_markers = ("change", "replace", "development", "example", "test-only")
        if len(secret) < 32 or any(
            marker in secret.casefold() for marker in unsafe_secret_markers
        ):
            raise ValueError("production session_secret must be a strong random value")

        unsafe_hosts = {"", "*", "localhost", "127.0.0.1", "testserver"}
        if not self.allowed_hosts or any(
            host.strip().casefold() in unsafe_hosts for host in self.allowed_hosts
        ):
            raise ValueError("production allowed_hosts must be explicit LAN host names")

        if "asset_root" not in self.model_fields_set:
            raise ValueError("production asset_root must be explicitly configured")
        if not self.asset_root.is_absolute() or self.asset_root == Path("/"):
            raise ValueError("production asset_root must be a dedicated absolute path")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
