from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from app.assets.router import create_assets_router
from app.approvals.router import create_approvals_router
from app.audit.router import create_audit_router
from app.api.errors import install_api_error_handling
from app.config import Settings, get_settings
from app.database import DatabaseResources, bootstrap_database
from app.documents.router import create_documents_router
from app.auth.router import create_auth_router
from app.health.router import DatabaseProbe, create_health_router, probe_database
from app.jobs.router import create_crop_jobs_router, create_jobs_router
from app.maintenance.service import enforce_maintenance_mode
from app.observability.logging import install_request_observability
from app.observability.metrics import MetricsRegistry, create_metrics_router
from app.papers.router import create_papers_router
from app.releases.router import create_releases_router
from app.reviews.router import create_reviews_router
from app.users.router import create_users_router
from app.structures.router import create_structures_router
from app.compounds.router import create_compounds_router
from app.evidence.router import create_evidence_router
from app.activities.router import create_activities_router
from app.admin.router import create_admin_router
from app.lineages.router import create_lineages_router
from app.visual_objects.router import create_visual_regions_router
from app.visual_objects.objects_router import create_visual_objects_router
from app.molecule_proposals.router import create_molecule_proposals_router


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
        dependencies=[Depends(enforce_maintenance_mode)],
    )
    application.state.settings = runtime_settings
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
    application.include_router(
        create_admin_router(runtime_settings, database_probe=database_probe),
    )
    application.include_router(create_jobs_router(runtime_settings))
    application.include_router(create_crop_jobs_router(runtime_settings))
    application.include_router(create_assets_router())
    application.include_router(
        create_approvals_router(runtime_settings.session_secret.get_secret_value())
    )
    application.include_router(create_audit_router())
    application.include_router(create_releases_router())
    application.include_router(create_papers_router())
    application.include_router(create_documents_router())
    application.include_router(
        create_reviews_router(runtime_settings.session_secret.get_secret_value())
    )
    application.include_router(
        create_visual_regions_router(runtime_settings.session_secret.get_secret_value())
    )
    application.include_router(
        create_visual_objects_router(runtime_settings.session_secret.get_secret_value())
    )
    application.include_router(
        create_molecule_proposals_router(runtime_settings.session_secret.get_secret_value())
    )
    application.include_router(
        create_structures_router(
            runtime_settings.session_secret.get_secret_value(),
            runtime_settings.asset_root,
        )
    )
    application.include_router(
        create_compounds_router(runtime_settings.session_secret.get_secret_value())
    )
    application.include_router(
        create_evidence_router(runtime_settings.session_secret.get_secret_value())
    )
    application.include_router(
        create_activities_router(runtime_settings.session_secret.get_secret_value())
    )
    application.include_router(
        create_lineages_router(runtime_settings.session_secret.get_secret_value())
    )
    return application


app = create_app()
