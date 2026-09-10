from __future__ import annotations

import os
from collections.abc import Callable

import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings


DatabaseProbe = Callable[[str], bool]


def probe_database(database_url: str) -> bool:
    """Return whether PostgreSQL accepts a minimal connection."""

    connection_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(connection_url, connect_timeout=2) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)


def create_health_router(
    settings: Settings,
    database_probe: DatabaseProbe,
) -> APIRouter:
    router = APIRouter(prefix="/health", tags=["system"])

    @router.get("/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @router.get("/ready")
    async def ready() -> JSONResponse:
        asset_ready = (
            settings.asset_root.is_dir()
            and os.access(settings.asset_root, os.R_OK | os.X_OK)
        )
        try:
            database_ready = bool(
                await run_in_threadpool(database_probe, settings.database_url)
            )
        except Exception:
            database_ready = False

        checks = {
            "asset_root": {"status": "ok" if asset_ready else "unavailable"},
            "database": {"status": "ok" if database_ready else "unavailable"},
        }
        available = asset_ready and database_ready
        return JSONResponse(
            status_code=200 if available else 503,
            content={"status": "ready" if available else "unavailable", "checks": checks},
        )

    return router
