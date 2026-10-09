from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from app.activities.router import create_activities_router
from app.ai_prefill.router import AiPrefillDispatch, create_ai_prefill_router
from app.ai_prefill.assistance_router import create_assistance_router
from app.ai_prefill.preview_guard import enforce_preview_identity
from app.ai_prefill.preview_http_limits import PreviewRequestBodyLimitMiddleware
from app.ai_prefill.preview_identity import PreviewIdentityError, verify_preview_connection
from app.assets.router import create_assets_router
from app.audit.router import create_audit_router
from app.api.errors import install_api_error_handling
from app.auth.router import create_auth_router
from app.catalog.router import create_catalog_router
from app.compounds.highlights import create_highlights_router
from app.compounds.router import create_compounds_router
from app.config import Settings, get_settings
from app.database import DatabaseResources, bootstrap_database
from app.evidence.router import create_evidence_router
from app.health.router import DatabaseProbe, create_health_router, probe_database
from app.documents.router import create_documents_router
from app.lineages.router import create_lineages_router
from app.maintenance.service import enforce_maintenance_mode
from app.observability.logging import install_request_observability
from app.observability.metrics import MetricsRegistry, create_metrics_router
from app.operations.router import create_operations_router
from app.publications.admin_router import create_admin_publications_router
from app.publications.router import create_publications_router
from app.structures.router import create_structures_router
from app.structure_images.router import create_structure_images_router
from app.users.router import create_users_router
from app.workspaces.router import create_workspaces_router


DatabaseBootstrap = Callable[[Settings], DatabaseResources | None]


def create_app(
    *,
    settings: Settings | None = None,
    database_probe: DatabaseProbe = probe_database,
    database_bootstrap: DatabaseBootstrap = bootstrap_database,
    ai_prefill_dispatch: AiPrefillDispatch | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()

    def verify_preview_resources(resources: DatabaseResources) -> None:
        with resources.engine.connect() as connection:
            verify_preview_connection(runtime_settings, connection)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resources = await run_in_threadpool(database_bootstrap, runtime_settings)
        ai_coordinator = None
        try:
            if runtime_settings.environment == "preview" and resources is None:
                raise PreviewIdentityError("Preview requires database resources")
            if resources is not None:
                if runtime_settings.environment == "preview":
                    await run_in_threadpool(verify_preview_resources, resources)
                application.state.database_engine = resources.engine
                application.state.session_factory = resources.session_factory
                if runtime_settings.ai_task_worker_enabled:
                    from app.ai_tasks.coordinator import AiTaskCoordinator
                    ai_coordinator = AiTaskCoordinator(resources.session_factory, runtime_settings)
                    ai_coordinator.start()
            yield
        finally:
            if ai_coordinator is not None:
                await run_in_threadpool(ai_coordinator.stop)
            if resources is not None:
                await run_in_threadpool(resources.close)

    application = FastAPI(
        title="LeadTrace API",
        version="0.1.0",
        docs_url="/api/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
        dependencies=[Depends(enforce_preview_identity), Depends(enforce_maintenance_mode)],
    )
    application.state.settings = runtime_settings
    if runtime_settings.environment == "preview":
        application.add_middleware(PreviewRequestBodyLimitMiddleware)
    install_api_error_handling(application)
    metrics_registry = MetricsRegistry()
    application.state.metrics_registry = metrics_registry
    install_request_observability(application, metrics_registry)
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=runtime_settings.allowed_hosts,
    )
    application.include_router(
        create_health_router(runtime_settings, database_probe),
    )
    application.include_router(
        create_metrics_router(metrics_registry, runtime_settings.metrics_bearer_token)
    )
    application.include_router(create_auth_router(runtime_settings))
    application.include_router(create_users_router(runtime_settings))
    from app.workspaces.lifecycle_router import create_lifecycle_router
    application.include_router(create_lifecycle_router(runtime_settings))
    from app.ai_tasks.router import create_ai_tasks_router
    application.include_router(create_ai_tasks_router(runtime_settings))
    application.include_router(create_assets_router())
    application.include_router(create_audit_router())
    application.include_router(
        create_operations_router(
            runtime_settings,
            database_probe=database_probe,
        )
    )
    application.include_router(create_catalog_router(runtime_settings))
    application.include_router(
        create_ai_prefill_router(runtime_settings, ai_prefill_dispatch)
    )
    application.include_router(create_assistance_router(runtime_settings))
    from app.ai_prefill.provenance import create_provenance_router
    application.include_router(create_provenance_router(runtime_settings))
    application.include_router(create_workspaces_router(runtime_settings))
    application.include_router(create_compounds_router(runtime_settings))
    application.include_router(create_highlights_router(runtime_settings))
    application.include_router(create_structures_router(runtime_settings))
    application.include_router(create_structure_images_router(runtime_settings))
    application.include_router(create_lineages_router(runtime_settings))
    application.include_router(create_evidence_router(runtime_settings))
    application.include_router(create_activities_router(runtime_settings))
    application.include_router(create_admin_publications_router(runtime_settings))
    application.include_router(create_publications_router())
    application.include_router(create_documents_router())
    return application


app = create_app()
