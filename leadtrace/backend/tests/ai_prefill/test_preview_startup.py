import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from app.ai_prefill.preview_identity import PreviewIdentityError
from app.ai_prefill.preview_models import PreviewMarker
from app.main import create_app


def rewrite_registry(settings, **changes):
    path = settings.preview_registry_path
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("drift", ["baseline", "missing_marker", "initializing", "database", "source"])
def test_preview_startup_rejects_identity_drift(preview_settings, preview_session_factory, drift):
    if drift in {"baseline", "missing_marker"}:
        with preview_session_factory.begin() as session:
            if drift == "baseline":
                session.execute(update(PreviewMarker).values(baseline_sha256="f" * 64))
            else:
                session.execute(delete(PreviewMarker))
    else:
        changes = {
            "initializing": {"state": "initializing"},
            "database": {"database_name": "different_preview"},
            "source": {"source_root": str(preview_settings.asset_root)},
        }
        rewrite_registry(preview_settings, **changes[drift])
    with pytest.raises(PreviewIdentityError):
        with TestClient(create_app(settings=preview_settings)):
            pass


def test_preview_startup_accepts_matching_instance(preview_settings):
    with TestClient(create_app(settings=preview_settings)) as client:
        assert client.get("/health/live").status_code == 200


def test_preview_drift_after_startup_blocks_auth_writes(preview_settings):
    with TestClient(create_app(settings=preview_settings), raise_server_exceptions=False) as client:
        rewrite_registry(preview_settings, baseline_sha256="f" * 64)
        response = client.post("/api/v1/auth/login", json={"username": "unknown", "password": "anything"})
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "PREVIEW_IDENTITY_MISMATCH"


@pytest.mark.parametrize("field", ["asset_root", "source_root", "artifact_root"])
def test_preview_startup_rejects_registry_path_drift(preview_settings, field):
    rewrite_registry(preview_settings, **{field: "/tmp/unknown-preview-root"})
    with pytest.raises(PreviewIdentityError):
        with TestClient(create_app(settings=preview_settings)):
            pass


def test_preview_bootstrap_does_not_claim_unmarked_database(preview_settings, preview_session_factory):
    from sqlalchemy import func, select
    from app.database import bootstrap_database
    with preview_session_factory.begin() as session:
        session.execute(delete(PreviewMarker))
    with pytest.raises(PreviewIdentityError):
        bootstrap_database(preview_settings)
    with preview_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PreviewMarker)) == 0


def test_direct_apply_rechecks_identity_before_any_scientific_write(preview_settings, preview_ai_context):
    from sqlalchemy import func, select
    from app.ai_prefill.preview_application import PreviewApplicationService
    from app.ai_prefill.preview_models import ApplicationReceipt
    from app.ai_prefill.assistance_validation import validate_candidate
    from app.ai_prefill.contracts import AiPrefillPayload
    from app.ai_prefill.models import AiExtractionRun
    from app.compounds.models import Compound
    from .test_preview_application import make_candidate
    from .test_contract import complete_payload
    candidate = make_candidate(AiPrefillPayload.model_validate(complete_payload()))
    rewrite_registry(preview_settings, baseline_sha256="f" * 64)
    with pytest.raises(PreviewIdentityError):
        with preview_ai_context.session_factory.begin() as session:
            PreviewApplicationService(settings=preview_settings).apply(
                session, instance_id=preview_settings.preview_instance_id,
                idempotency_key="must-not-write", candidate=candidate,
                validation_report=validate_candidate(candidate),
                actor_id=preview_ai_context.admin_id,
                workspace_id=preview_ai_context.workspace_id, expected_workspace_version=1,
            )
    with preview_ai_context.session_factory() as session:
        for model in (AiExtractionRun, Compound, ApplicationReceipt):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_preview_startup_requires_database_resources(preview_settings):
    with pytest.raises(PreviewIdentityError):
        with TestClient(create_app(settings=preview_settings, database_bootstrap=lambda _: None)):
            pass


def test_deleted_marker_after_startup_blocks_auth_without_writes(preview_settings, preview_session_factory):
    from sqlalchemy import func, select
    from app.auth.models import LoginAttempt
    with TestClient(create_app(settings=preview_settings), raise_server_exceptions=False) as client:
        with preview_session_factory.begin() as session:
            before = session.scalar(select(func.count()).select_from(LoginAttempt))
            session.execute(delete(PreviewMarker))
        response = client.post("/api/v1/auth/login", json={"username": "unknown", "password": "anything"})
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "PREVIEW_IDENTITY_MISMATCH"
        with preview_session_factory() as session:
            assert session.scalar(select(func.count()).select_from(LoginAttempt)) == before


@pytest.mark.parametrize("root", ["assets", "sources", "artifacts"])
def test_preview_startup_requires_provisioned_directories(preview_settings, root):
    (preview_settings.asset_root.parent / root).rmdir()
    with pytest.raises(PreviewIdentityError):
        with TestClient(create_app(settings=preview_settings)):
            pass
    assert not (preview_settings.asset_root.parent / root).exists()


def test_extra_schema_revision_after_startup_blocks_requests(preview_settings, preview_session_factory):
    from sqlalchemy import text
    with TestClient(create_app(settings=preview_settings), raise_server_exceptions=False) as client:
        with preview_session_factory.begin() as session:
            session.execute(text("INSERT INTO alembic_version (version_num) VALUES ('unexpected_branch')"))
        response = client.post("/api/v1/auth/login", json={"username": "unknown", "password": "anything"})
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "PREVIEW_IDENTITY_MISMATCH"
