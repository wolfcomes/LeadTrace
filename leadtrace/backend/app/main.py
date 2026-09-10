from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings
from app.health.router import DatabaseProbe, create_health_router, probe_database


def create_app(
    *,
    settings: Settings | None = None,
    database_probe: DatabaseProbe = probe_database,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    application = FastAPI(
        title="LeadTrace API",
        version="0.1.0",
        docs_url="/api/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=runtime_settings.allowed_hosts,
    )
    application.include_router(
        create_health_router(runtime_settings, database_probe),
    )
    return application


app = create_app()
