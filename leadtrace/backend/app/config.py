from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration with stricter production invariants."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LEADTRACE_",
        extra="ignore",
    )

    environment: Literal["development", "test", "preview", "production"] = "development"
    database_url: str = (
        "postgresql+psycopg://leadtrace:leadtrace-development-only@postgres/leadtrace"
    )
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    database_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)
    redis_url: str = "redis://redis:6379/0"
    session_secret: SecretStr = SecretStr("development-only-not-for-production")
    default_account_password: SecretStr | None = None
    metrics_bearer_token: SecretStr | None = None
    admin_reauthentication_minutes: int = Field(default=10, ge=1, le=60)
    https_enabled: bool = False
    nginx_internal_transfer: bool = False
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    trusted_proxy_addresses: list[str] = []
    asset_root: Path = Path("/var/lib/leadtrace/assets")
    source_roots: dict[str, Path] = Field(default_factory=dict)
    article_archive_root: Path = Path('/var/lib/leadtrace/article-archives')
    ai_task_root: Path = Path('/var/lib/leadtrace/ai-tasks')
    ai_task_worker_enabled: bool = False
    ai_task_python: Path | None = None
    ai_task_presets: list[dict[str, object]] = Field(default_factory=list)
    ai_task_inventory_roots: list[Path] = Field(default_factory=list)
    ai_prefill_engine: str = "legacy_pipeline"
    ai_prefill_engine_version: str = "pilot-v1"
    ai_prefill_legacy_root: Path | None = None
    preview_instance_id: UUID | None = None
    preview_baseline_sha256: str | None = None
    preview_artifact_root: Path | None = None
    preview_registry_path: Path | None = None
    deployment_profile: str = "default"

    @field_validator(
        "ai_prefill_legacy_root",
        mode="before",
    )
    @classmethod
    def normalize_optional_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("preview_baseline_sha256")
    @classmethod
    def validate_preview_baseline(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError("preview_baseline_sha256 must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_ai_storage(self) -> "Settings":
        roots = {"article_archive_root": self.article_archive_root, "ai_task_root": self.ai_task_root}
        for name, path in roots.items():
            if not path.is_absolute() or path == Path("/") or ".." in path.parts:
                raise ValueError(f"{name} must be a dedicated absolute path")
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise ValueError(f"{name} must not contain symlinks")
        protected = [self.asset_root, *self.source_roots.values()]
        if self.preview_artifact_root is not None:
            protected.append(self.preview_artifact_root)
        for name, path in roots.items():
            for other in [*protected, *(v for k, v in roots.items() if k != name)]:
                if path.is_relative_to(other) or other.is_relative_to(path):
                    raise ValueError(f"{name} must not overlap source, asset, artifact or other task storage")
        return self

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

        default_account_password = (
            self.default_account_password.get_secret_value()
            if self.default_account_password is not None
            else ""
        )
        if len(default_account_password) < 6 or any(
            marker in default_account_password.casefold()
            for marker in unsafe_secret_markers
        ):
            raise ValueError(
                "production default_account_password must contain at least 6 characters"
            )

        metrics_token = (
            self.metrics_bearer_token.get_secret_value()
            if self.metrics_bearer_token is not None
            else ""
        )
        if len(metrics_token) < 32:
            raise ValueError("production metrics_bearer_token must be a strong random value")

        unsafe_hosts = {"", "*", "localhost", "127.0.0.1", "testserver"}
        if not self.allowed_hosts or any(
            host.strip().casefold() in unsafe_hosts for host in self.allowed_hosts
        ):
            raise ValueError("production allowed_hosts must be explicit LAN host names")

        if "asset_root" not in self.model_fields_set:
            raise ValueError("production asset_root must be explicitly configured")
        if not self.asset_root.is_absolute() or self.asset_root == Path("/"):
            raise ValueError("production asset_root must be a dedicated absolute path")
        if any(
            not path.is_absolute() or path == Path("/")
            for path in self.source_roots.values()
        ):
            raise ValueError("production source_roots must be dedicated absolute paths")
        optional_paths = {
            "ai_prefill_legacy_root": self.ai_prefill_legacy_root,
            "preview_artifact_root": self.preview_artifact_root,
        }
        for name, path in optional_paths.items():
            if path is not None and (not path.is_absolute() or path == Path("/")):
                raise ValueError(
                    f"production {name} must be a dedicated absolute path"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
