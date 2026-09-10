from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.database import DatabaseResources, bootstrap_database
from app.auth.router import create_auth_router
from app.health.router import DatabaseProbe, create_health_router, probe_database
from app.users.router import create_users_router


DatabaseBootstrap = Callable[[Settings], DatabaseResources | None]


def create_app(
    *,
    settings: Settings | None = None,
    database_probe: DatabaseProbe = probe_database,
    database_bootstrap: DatabaseBootstrap = bootstrap_database,
) -> FastAPI:
    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resources = await run_in_threadpool(database_bootstrap, runtime_settings)
        try:
            if resources is not None:
                application.state.database_engine = resources.engine
                application.state.session_factory = resources.session_factory
            yield
        finally:
            if resources is not None:
                await run_in_threadpool(resources.close)

    application = FastAPI(
        title="LeadTrace API",
        version="0.1.0",
        docs_url="/api/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=runtime_settings.allowed_hosts,
    )
    application.include_router(
        create_health_router(runtime_settings, database_probe),
    )
    application.include_router(create_auth_router(runtime_settings))
    application.include_router(create_users_router(runtime_settings))
    return application


app = create_app()
