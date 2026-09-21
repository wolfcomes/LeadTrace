"""Preview routes exercised with real sessions and an isolated PostgreSQL DB."""
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai_prefill.assistance_contracts import with_computed_hashes
from app.ai_prefill.assistance_verification import verify_application_receipt
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.models import AiExtractionRun
from app.ai_prefill.preview_models import ApplicationReceipt, PreviewMarker
from app.compounds.models import Compound
from app.main import create_app

from .test_apply import AiContext
from .test_contract import complete_payload
from .test_preview_application import make_candidate

PREFIX = "/api/v2/admin/ai-prefill"


@pytest.fixture
def preview_client(preview_ai_context: AiContext, preview_settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings=preview_settings), raise_server_exceptions=False) as client:
        yield client


def login(client: TestClient, *, reviewer: bool = False) -> dict[str, str]:
    role = "reviewer" if reviewer else "admin"
    response = client.post("/api/v1/auth/login", json={
        "username": f"ai.prefill.{role}",
        "password": f"AI prefill {role.title()} password 2026!",
    })
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def candidate_json() -> dict:
    return make_candidate(AiPrefillPayload.model_validate(complete_payload())).model_dump(mode="json")


def test_validation_requires_csrf_without_writing_report(preview_client, tmp_path):
    headers = login(preview_client)
    candidate = candidate_json()
    created = preview_client.post(f"{PREFIX}/candidates", json={"candidate": candidate}, headers=headers)
    assert created.status_code == 201, created.text
    endpoint = f"{PREFIX}/candidates/{candidate['candidate_id']}/validations"
    params = {"experiment_id": candidate["experiment_id"]}
    for rejected_headers in ({}, {"X-CSRF-Token": "invalid"}):
        response = preview_client.post(endpoint, params=params, json={}, headers=rejected_headers)
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "CSRF_VALIDATION_FAILED"
    assert not list((tmp_path / "artifacts").rglob("validations/*.json"))
    response = preview_client.post(endpoint, params=params, json={}, headers=headers)
    assert response.status_code == 200, response.text
    assert len(list((tmp_path / "artifacts").rglob("validations/*.json"))) == 1


def test_preview_http_import_apply_replay_and_verify(preview_client, preview_ai_context):
    headers = login(preview_client)
    assert preview_client.get(f"{PREFIX}/contracts").status_code == 200
    candidate = candidate_json()
    params = {"experiment_id": candidate["experiment_id"]}
    endpoint = f"{PREFIX}/candidates/{candidate['candidate_id']}"
    created = preview_client.post(f"{PREFIX}/candidates", json={"candidate": candidate}, headers=headers)
    assert created.status_code == 201, created.text
    replay = preview_client.post(f"{PREFIX}/candidates", json={"candidate": candidate}, headers=headers)
    assert replay.status_code == 201 and replay.json()["replayed"]
    assert preview_client.get(endpoint, params=params).json()["candidate"] == created.json()["candidate"]
    with preview_ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Compound)) == 0
        assert session.scalar(select(func.count()).select_from(AiExtractionRun)) == 0
    validation = preview_client.post(endpoint + "/validations", params=params, json={}, headers=headers)
    assert validation.status_code == 200, validation.text
    body = {
        "validation_report": validation.json()["report"],
        "idempotency_key": "http-apply-1",
        "paper_id": str(preview_ai_context.paper_id),
        "workspace_id": str(preview_ai_context.workspace_id),
        "expected_workspace_version": 1,
    }
    for rejected_headers in ({}, {"X-CSRF-Token": "invalid"}):
        rejected = preview_client.post(
            endpoint + "/preview-applications", params=params, json=body,
            headers=rejected_headers,
        )
        assert rejected.status_code == 403, rejected.text
    with preview_ai_context.session_factory() as session:
        for model in (AiExtractionRun, Compound, ApplicationReceipt):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    applied = preview_client.post(endpoint + "/preview-applications", params=params, json=body, headers=headers)
    assert applied.status_code == 200, applied.text
    application_id = applied.json()["application_id"]
    reviewer_url = f"/review/papers/{preview_ai_context.paper_id}?workspace={preview_ai_context.workspace_id}"
    assert applied.json()["reviewer_url"] == reviewer_url
    for ref in ("compound:lead-1", "compound:18"):
        compound_id = applied.json()["receipt"]["entity_map"][f"/compounds/{ref}"]
        depiction = preview_client.get(f"/api/v2/compounds/{compound_id}/structure/depiction")
        assert depiction.status_code == 200, depiction.text
        assert depiction.headers["content-type"] == "image/png"
        assert depiction.content.startswith(b"\x89PNG")
    replay = preview_client.post(endpoint + "/preview-applications", params=params, json=body, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent"]
    assert replay.json()["application_id"] == application_id
    fetched = preview_client.get(f"{PREFIX}/applications/{application_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["reviewer_url"] == reviewer_url
    with preview_ai_context.session_factory() as session:
        receipt = session.scalar(select(ApplicationReceipt).where(
            ApplicationReceipt.application_id == UUID(application_id),
        ))
        assert receipt is not None
        verification = verify_application_receipt(session, receipt)
        assert verification.status == "committed", verification.details
        assert session.scalar(select(func.count()).select_from(ApplicationReceipt)) == 1
        assert session.scalar(select(func.count()).select_from(AiExtractionRun)) == 1
    # A second instance marker makes the entire DB ambiguous and inaccessible.
    with preview_ai_context.session_factory.begin() as session:
        other_instance = uuid4()
        session.add(PreviewMarker(
            instance_id=other_instance,
            baseline_sha256="c" * 64,
            schema_revision="0026_ai_prefill_preview_receipts",
        ))
        session.flush()
        receipt = session.scalar(select(ApplicationReceipt).where(
            ApplicationReceipt.application_id == UUID(application_id),
        ))
        receipt.instance_id = other_instance
    assert preview_client.get(f"{PREFIX}/applications/{application_id}").status_code == 503


def test_preview_http_rejects_unauthorized_requests(preview_client):
    assert preview_client.get(f"{PREFIX}/contracts").status_code == 401
    login(preview_client)
    response = preview_client.post(f"{PREFIX}/candidates", json={"candidate": candidate_json()})
    assert response.status_code == 403
    headers = login(preview_client, reviewer=True)
    assert preview_client.get(f"{PREFIX}/contracts").status_code == 403
    assert preview_client.post(f"{PREFIX}/candidates", json={"candidate": candidate_json()}, headers=headers).status_code == 403


def test_preview_http_invalid_hash_is_422(preview_client):
    headers = login(preview_client)
    candidate = candidate_json()
    candidate["payload"]["bibliography"]["title"] = "Tampered after hashing"
    response = preview_client.post(f"{PREFIX}/candidates", json={"candidate": candidate}, headers=headers)
    assert response.status_code == 422, response.text


def test_preview_http_source_mismatch_is_422_without_writes(preview_client, preview_ai_context):
    headers = login(preview_client)
    candidate = make_candidate(AiPrefillPayload.model_validate(complete_payload()))
    candidate = with_computed_hashes(candidate.model_copy(update={
        "source": candidate.source.model_copy(update={"source_sha256": "f" * 64}),
    }))
    created = preview_client.post(f"{PREFIX}/candidates", json={"candidate": candidate.model_dump(mode="json")}, headers=headers)
    assert created.status_code == 201, created.text
    params = {"experiment_id": candidate.experiment_id}
    endpoint = f"{PREFIX}/candidates/{candidate.candidate_id}"
    validation = preview_client.post(endpoint + "/validations", params=params, json={}, headers=headers)
    response = preview_client.post(endpoint + "/preview-applications", params=params, headers=headers, json={
        "validation_report": validation.json()["report"],
        "idempotency_key": "source-mismatch",
        "workspace_id": str(preview_ai_context.workspace_id),
        "expected_workspace_version": 1,
    })
    assert response.status_code == 422, response.text
    with preview_ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Compound)) == 0
        assert session.scalar(select(func.count()).select_from(ApplicationReceipt)) == 0


def test_preview_blocks_legacy_worker_dispatch(preview_client, preview_ai_context):
    headers = login(preview_client)
    endpoint = f"/api/v2/admin/papers/{preview_ai_context.paper_id}/ai-prefill"
    status = preview_client.get(endpoint)
    assert status.status_code == 200, status.text
    assert status.json()["can_start"] is False
    assert status.json()["blocked_reason"] == "Preview requires candidate application"
    queued = preview_client.post(endpoint, headers=headers)
    assert queued.status_code == 409, queued.text
    assert queued.json()["code"] == "AI_PREFILL_UNAVAILABLE"
    with preview_ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AiExtractionRun)) == 0


@pytest.mark.parametrize("transport", ["length", "missing", "forged"])
def test_preview_rejects_oversize_body_before_candidate_or_scientific_writes(
    preview_client, preview_ai_context, preview_settings, transport,
):
    import json
    headers = {**login(preview_client), "Content-Type": "application/json"}
    encoded = json.dumps({"candidate": candidate_json()}).encode()
    body = encoded + b" " * (2 * 1024 * 1024 + 1 - len(encoded))
    if transport == "missing":
        content = iter((body[:1024 * 1024], body[1024 * 1024:]))
    else:
        content = body
        if transport == "forged":
            headers["Content-Length"] = "1"
    response = preview_client.post(f"{PREFIX}/candidates", content=content, headers=headers)
    assert response.status_code == 413, response.text[:300]
    assert response.json()["code"] == "PREVIEW_REQUEST_TOO_LARGE"
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    assert not list(preview_settings.preview_artifact_root.rglob("candidate.json"))
    with preview_ai_context.session_factory() as session:
        for model in (Compound, AiExtractionRun, ApplicationReceipt):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_preview_accepts_body_at_exact_limit(preview_client):
    import json
    headers = {**login(preview_client), "Content-Type": "application/json"}
    encoded = json.dumps({"candidate": candidate_json()}).encode()
    body = encoded + b" " * (2 * 1024 * 1024 - len(encoded))
    response = preview_client.post(f"{PREFIX}/candidates", content=body, headers=headers)
    assert response.status_code == 201, response.text[:300]


def test_preview_rejects_excessive_candidate_objects_without_writing_artifacts(preview_client, preview_settings):
    from app.ai_prefill.contracts import AiPrefillPayload
    headers = login(preview_client)
    value = make_candidate(AiPrefillPayload.model_validate({
        "schema_version": 1,
        "compounds": [{"ref": f"c{index}", "compound_label": str(index), "structure": {"smiles": "CCO"}}
                      for index in range(2501)],
    }))
    response = preview_client.post(f"{PREFIX}/candidates", json={"candidate": value.model_dump(mode="json")}, headers=headers)
    assert response.status_code == 422, response.text[:300]
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert not list(preview_settings.preview_artifact_root.rglob("candidate.json"))
