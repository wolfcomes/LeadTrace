from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from uuid import UUID, uuid4

import pymupdf
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import ClientDisconnect

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore
from app.catalog.models import PaperSource
from app.compounds.models import Compound
from app.jobs.execution import render_pdf_crop
from app.jobs.service import PDF_RENDERER_VERSION, CropRequest, CropService
from app.papers.models import Paper
from app.security.policies import Principal
from app.structure_images.models import StructureSourceImage
from app.structure_images.schemas import NormalizedBBox
from app.users.models import UserRole
from app.workspaces.models import (
    ChangeEvent,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)


def _create_compound(context, csrf: str, *, aggregate=None, version: int = 1):
    aggregate = aggregate or context.first
    response = context.client.post(
        f"/api/v2/workspaces/{aggregate.workspace_id}/compounds",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": version,
            "compound_label": f"source-{uuid4().hex[:8]}",
        },
    )
    assert response.status_code == 201
    return response.json()["compound"]


def _source_sha(context, paper_id) -> str:
    with context.session_factory() as session:
        return str(
            session.scalar(
                select(PaperSource.sha256)
                .join(Paper, Paper.source_id == PaperSource.id)
                .where(Paper.id == paper_id)
            )
        )


def _create_image(context, csrf: str, compound_id: str, *, version: int, **changes):
    payload = {
        "expected_workspace_version": version,
        "source_sha256": _source_sha(context, context.first.paper_id),
        "page_number": 2,
        "bbox": {"x0": 0.2, "y0": 0.25, "x1": 0.7, "y1": 0.8},
        "source_context": "Scheme 2",
        "label": "Compound 18",
        "reviewer_note": "Original drawing",
    }
    payload.update(changes)
    return context.client.post(
        f"/api/v2/compounds/{compound_id}/source-images",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )


async def _disconnect_during_response_body(response) -> None:
    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("client disconnected")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "root_path": "",
    }
    await response(scope, receive, send)


def test_create_read_list_update_retry_and_delete_source_image(science_api_context):
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)

    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    body = created.json()
    image = body["source_image"]
    assert body["workspace_version"] == 3
    assert image["compound_id"] == compound["id"]
    assert image["crop_status"] == "ready"
    assert image["crop_asset_id"] is not None
    assert image["bbox"] == {"x0": 0.2, "y0": 0.25, "x1": 0.7, "y1": 0.8}
    assert "/tmp/" not in created.text
    assert str(context.asset_root) not in created.text

    listing = context.client.get(
        f"/api/v2/compounds/{compound['id']}/source-images"
    )
    detail = context.client.get(
        f"/api/v2/structure-source-images/{image['id']}"
    )
    assert listing.status_code == detail.status_code == 200
    assert listing.json()["items"] == [image]
    assert listing.json()["workspace_version"] == 3
    assert detail.json()["source_image"] == image

    updated = context.client.patch(
        f"/api/v2/structure-source-images/{image['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 3,
            "label": "Compound 18a",
            "reviewer_note": None,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["workspace_version"] == 4
    assert updated.json()["source_image"]["label"] == "Compound 18a"
    assert updated.json()["source_image"]["reviewer_note"] is None
    assert updated.json()["source_image"]["crop_asset_id"] == image["crop_asset_id"]

    no_op = context.client.patch(
        f"/api/v2/structure-source-images/{image['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 4,
            "label": "Compound 18a",
            "reviewer_note": None,
        },
    )
    assert no_op.status_code == 200
    assert no_op.json()["workspace_version"] == 4

    retried = context.client.post(
        f"/api/v2/structure-source-images/{image['id']}/retry",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 4},
    )
    assert retried.status_code == 200
    assert retried.json()["workspace_version"] == 4
    assert retried.json()["source_image"]["crop_asset_id"] == image["crop_asset_id"]

    deleted = context.client.request(
        "DELETE",
        f"/api/v2/structure-source-images/{image['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 4},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {
        "deleted_source_image_id": image["id"],
        "workspace_version": 5,
    }

    with context.session_factory() as session:
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        events = list(
            session.scalars(
                select(ChangeEvent)
                .where(ChangeEvent.workspace_id == context.first.workspace_id)
                .order_by(ChangeEvent.occurred_at, ChangeEvent.id)
            )
        )
        assert workspace is not None and workspace.version == 5
        assert [event.action for event in events] == [
            "compound.create",
            "structure_source_image.create",
            "structure_source_image.update",
            "structure_source_image.delete",
        ]
        assert session.get(StructureSourceImage, image["id"]) is None


def test_locator_validation_rejects_page_bbox_hash_and_duplicate_occurrence(
    science_api_context,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    valid = _create_image(context, csrf, compound["id"], version=2)
    assert valid.status_code == 201

    invalid_payloads = [
        {"page_number": 4},
        {"bbox": {"x0": 0.5, "y0": 0.2, "x1": 0.5, "y1": 0.8}},
        {"bbox": {"x0": -0.1, "y0": 0.2, "x1": 0.5, "y1": 0.8}},
        {"source_sha256": "f" * 64},
    ]
    for changes in invalid_payloads:
        response = _create_image(context, csrf, compound["id"], version=3, **changes)
        assert response.status_code == 422
        assert "/tmp/" not in response.text

    duplicate = _create_image(context, csrf, compound["id"], version=3)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "STRUCTURE_SOURCE_IMAGE_DUPLICATE"
    assert "uq_" not in duplicate.text

    with context.session_factory() as session:
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        count = session.scalar(
            select(func.count()).select_from(StructureSourceImage)
        )
        events = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert workspace is not None and workspace.version == 3
        assert count == 1
        assert events == 2


def test_duplicate_locator_closes_the_verified_source_snapshot(
    science_api_context,
    monkeypatch,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    snapshots = []
    real_open_snapshot = LocalAssetStore.open_snapshot

    def track_snapshot(store, *args, **kwargs):
        inspected, snapshot = real_open_snapshot(store, *args, **kwargs)
        snapshots.append(snapshot)
        return inspected, snapshot

    monkeypatch.setattr(LocalAssetStore, "open_snapshot", track_snapshot)
    duplicate = _create_image(context, csrf, compound["id"], version=3)

    assert duplicate.status_code == 409
    assert len(snapshots) == 1
    assert snapshots[0].closed is True


def test_source_image_hides_unassigned_and_cross_paper_compounds(
    science_api_context,
) -> None:
    context = science_api_context
    reviewer_csrf = context.login("science.api.reviewer")
    first_compound = _create_compound(context, reviewer_csrf)

    other_csrf = context.login("science.api.other")
    concealed = _create_image(context, other_csrf, first_compound["id"], version=2)
    assert concealed.status_code == 404

    second_compound = _create_compound(
        context,
        other_csrf,
        aggregate=context.second,
    )
    cross_paper = _create_image(
        context,
        other_csrf,
        second_compound["id"],
        version=2,
        source_sha256=_source_sha(context, context.first.paper_id),
    )
    assert cross_paper.status_code == 422
    assert cross_paper.json()["code"] == "STRUCTURE_SOURCE_MISMATCH"

    context.login("science.api.reviewer")
    detail = context.client.get(
        f"/api/v2/compounds/{second_compound['id']}/source-images"
    )
    assert detail.status_code == 404


def test_failed_crop_keeps_retryable_locator_with_null_asset(
    science_api_context,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    storage_key: str
    with context.session_factory.begin() as session:
        asset = session.get(Asset, context.first.asset_id)
        source = session.scalar(
            select(PaperSource).where(PaperSource.asset_id == context.first.asset_id)
        )
        assert asset is not None and source is not None
        storage_key = asset.storage_key
        invalid_pdf = b"%PDF-1.7\nthis is not renderable\n%%EOF\n"
        digest = hashlib.sha256(invalid_pdf).hexdigest()
        asset.sha256 = source.sha256 = digest
        asset.byte_size = source.byte_size = len(invalid_pdf)
        asset.page_count = source.page_count = 3
    source_path = Path(context.client.app.state.settings.source_roots["source_pdfs"])
    source_path = source_path.joinpath(*storage_key.split("/")[2:])
    source_path.write_bytes(invalid_pdf)

    response = _create_image(
        context,
        csrf,
        compound["id"],
        version=2,
        source_sha256=digest,
    )
    assert response.status_code == 201
    image = response.json()["source_image"]
    assert image["crop_status"] == "failed"
    assert image["crop_asset_id"] is None
    assert response.json()["workspace_version"] == 3

    retry = context.client.post(
        f"/api/v2/structure-source-images/{image['id']}/retry",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3},
    )
    assert retry.status_code == 200
    assert retry.json()["source_image"]["crop_status"] == "failed"
    assert retry.json()["source_image"]["crop_asset_id"] is None
    assert retry.json()["workspace_version"] == 3


def test_bbox_precision_is_rejected_before_create_or_update_persistence(
    science_api_context,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)

    rejected_create = _create_image(
        context,
        csrf,
        compound["id"],
        version=2,
        bbox={
            "x0": "0.123456789012",
            "y0": "0.25",
            "x1": "0.7",
            "y1": "0.8",
        },
    )
    assert rejected_create.status_code == 422

    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    image = created.json()["source_image"]
    rejected_update = context.client.patch(
        f"/api/v2/structure-source-images/{image['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 3,
            "bbox": {
                "x0": "0.2",
                "y0": "0.250000000001",
                "x1": "0.7",
                "y1": "0.8",
            },
        },
    )
    assert rejected_update.status_code == 422

    with context.session_factory() as session:
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        source_image = session.get(StructureSourceImage, image["id"])
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert workspace is not None and workspace.version == 3
        assert source_image is not None
        assert float(source_image.y0) == 0.25
        assert event_count == 2
    assert context.client.get(
        f"/api/v2/structure-source-images/{image['id']}/content"
    ).status_code == 200


def test_bbox_rejects_positive_area_that_collapses_at_database_scale() -> None:
    with pytest.raises(ValidationError, match="decimal places"):
        NormalizedBBox.model_validate(
            {
                "x0": "0.200000000001",
                "y0": "0.25",
                "x1": "0.200000000002",
                "y1": "0.8",
            }
        )


def test_signed_zero_bbox_is_canonicalized_for_crop_identity(
    science_api_context,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)

    created = _create_image(
        context,
        csrf,
        compound["id"],
        version=2,
        bbox={
            "x0": "-0.0000000000",
            "y0": "0.25",
            "x1": "0.7",
            "y1": "0.8",
        },
    )

    assert created.status_code == 201
    image = created.json()["source_image"]
    assert image["bbox"]["x0"] == 0
    assert context.client.get(
        f"/api/v2/structure-source-images/{image['id']}/content"
    ).status_code == 200
    bbox = NormalizedBBox.model_validate(
        {"x0": "-0.0000000000", "y0": "0.25", "x1": "0.7", "y1": "0.8"}
    )
    assert bbox.x0.is_zero() and not bbox.x0.is_signed()


def test_post_render_materialization_failure_keeps_retryable_locator(
    science_api_context,
    monkeypatch,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)

    def fail_materialization(*args, **kwargs):
        raise OSError("simulated managed storage failure")

    monkeypatch.setattr(CropService, "materialize_persisted", fail_materialization)
    try:
        response = _create_image(context, csrf, compound["id"], version=2)
    except OSError:
        pytest.fail("post-render storage failure escaped the locator mutation")

    assert response.status_code == 201
    image = response.json()["source_image"]
    assert response.json()["workspace_version"] == 3
    assert image["crop_status"] == "failed"
    assert image["crop_asset_id"] is None
    with context.session_factory() as session:
        source_image = session.get(StructureSourceImage, image["id"])
        assert source_image is not None
        assert source_image.crop_status.value == "failed"
        assert source_image.crop_asset_id is None

    monkeypatch.undo()
    retried = context.client.post(
        f"/api/v2/structure-source-images/{image['id']}/retry",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3},
    )
    assert retried.status_code == 200
    assert retried.json()["workspace_version"] == 4
    assert retried.json()["source_image"]["crop_status"] == "ready"
    assert retried.json()["source_image"]["crop_asset_id"] is not None


def test_asset_registration_failure_removes_unregistered_crop_file(
    science_api_context,
    monkeypatch,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    files_before = set(context.asset_root.rglob("*.png"))

    def fail_registration(*args, **kwargs):
        raise SQLAlchemyError("simulated Asset registration failure")

    monkeypatch.setattr(AssetService, "register_inspected", fail_registration)
    response = _create_image(context, csrf, compound["id"], version=2)

    assert response.status_code == 201
    image = response.json()["source_image"]
    assert image["crop_status"] == "failed"
    assert image["crop_asset_id"] is None
    assert set(context.asset_root.rglob("*.png")) == files_before
    with context.session_factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(Asset)
            .where(Asset.category == AssetCategory.EVIDENCE_CROP)
        ) == 0


def test_compound_delete_event_snapshots_every_cascaded_source_image(
    science_api_context,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    first = _create_image(context, csrf, compound["id"], version=2)
    second = _create_image(
        context,
        csrf,
        compound["id"],
        version=3,
        page_number=3,
    )
    assert first.status_code == second.status_code == 201

    deleted = context.client.request(
        "DELETE",
        f"/api/v2/compounds/{compound['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 4},
    )
    assert deleted.status_code == 200

    with context.session_factory() as session:
        event = session.scalar(
            select(ChangeEvent).where(
                ChangeEvent.workspace_id == context.first.workspace_id,
                ChangeEvent.action == "compound.delete",
            )
        )
        assert event is not None and event.before_value is not None
        snapshots = event.before_value["structure_source_images"]
        assert [snapshot["page_number"] for snapshot in snapshots] == [2, 3]
        assert all(snapshot["crop_asset_id"] for snapshot in snapshots)
        assert session.get(Compound, compound["id"]) is None
        assert session.scalar(
            select(func.count()).select_from(StructureSourceImage)
        ) == 0


def test_crop_content_is_scoped_to_exact_workspace_assignment(
    science_api_context,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    image = created.json()["source_image"]
    scoped_url = f"/api/v2/structure-source-images/{image['id']}/content"
    generic_url = f"/api/v1/assets/{image['crop_asset_id']}/content"

    assigned = context.client.get(scoped_url)
    assert assigned.status_code == 200
    assert assigned.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert assigned.headers["Cache-Control"] == "private, no-store"
    assert assigned.headers["X-Content-Type-Options"] == "nosniff"
    assert str(context.asset_root) not in assigned.text
    assert context.client.get(generic_url).status_code == 404

    for username, expected in (
        ("science.api.admin", 200),
        ("science.api.other", 404),
        ("science.api.visitor", 404),
    ):
        context.login(username)
        response = context.client.get(scoped_url)
        assert response.status_code == expected
        assert str(context.asset_root) not in response.text
        assert context.client.get(generic_url).status_code == 404

    context.login("science.api.admin")
    unknown = context.client.get(f"/api/v2/structure-source-images/{uuid4()}/content")
    assert unknown.status_code == 404
    assert str(context.asset_root) not in unknown.text

    csrf = context.login("science.api.reviewer")
    with context.session_factory.begin() as session:
        legacy_asset = session.get(Asset, image["crop_asset_id"])
        assert legacy_asset is not None
        legacy_asset.derivation_metadata = {
            key: value
            for key, value in legacy_asset.derivation_metadata.items()
            if key != "visibility_scope"
        }
        legacy_asset.access_level = AssetAccessLevel.ADMIN
    deleted = context.client.request(
        "DELETE",
        f"/api/v2/structure-source-images/{image['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3},
    )
    assert deleted.status_code == 200
    context.login("science.api.admin")
    assert context.client.get(generic_url).status_code == 404


@pytest.mark.parametrize(
    "tamper",
    ["category", "access_level", "source_asset_id", "crop_input_hash"],
)
def test_crop_content_rejects_asset_with_mismatched_provenance(
    science_api_context,
    tamper: str,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    image = created.json()["source_image"]

    with context.session_factory.begin() as session:
        asset = session.get(Asset, image["crop_asset_id"])
        assert asset is not None
        if tamper == "category":
            asset.category = AssetCategory.RDKIT_STRUCTURE
        elif tamper == "access_level":
            asset.access_level = AssetAccessLevel.ADMIN
        elif tamper == "source_asset_id":
            asset.source_asset_id = context.second.asset_id
        else:
            asset.derivation_metadata = {
                **asset.derivation_metadata,
                "crop_input_hash": "0" * 64,
            }

    response = context.client.get(
        f"/api/v2/structure-source-images/{image['id']}/content"
    )

    assert response.status_code == 404


def test_approved_workspace_crop_remains_readable_to_assigned_reviewer(
    science_api_context,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    image = created.json()["source_image"]
    scoped_url = f"/api/v2/structure-source-images/{image['id']}/content"

    with context.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        assert workspace is not None
        task = session.get(ReviewTask, workspace.review_task_id)
        assert task is not None
        workspace.state = WorkspaceState.APPROVED
        task.status = ReviewTaskState.APPROVED

    reviewer_response = context.client.get(scoped_url)
    context.login("science.api.admin")
    admin_response = context.client.get(scoped_url)

    assert reviewer_response.status_code == 200
    assert admin_response.status_code == 200


def test_crop_content_closes_verified_snapshot_on_client_disconnect(
    science_api_context,
    monkeypatch,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    image = created.json()["source_image"]
    snapshots = []
    real_open_snapshot = LocalAssetStore.open_snapshot

    def track_snapshot(store, *args, **kwargs):
        inspected, snapshot = real_open_snapshot(store, *args, **kwargs)
        snapshots.append(snapshot)
        return inspected, snapshot

    monkeypatch.setattr(LocalAssetStore, "open_snapshot", track_snapshot)
    endpoint = next(
        route.endpoint
        for route in context.client.app.routes
        if getattr(route, "path", None)
        == "/api/v2/structure-source-images/{source_image_id}/content"
    )
    with context.session_factory() as session:
        response = endpoint(
            source_image_id=UUID(image["id"]),
            session=session,
            principal=Principal(
                user_id=context.reviewer_id,
                role=UserRole.REVIEWER,
            ),
        )

    async def assert_disconnect_closes_snapshot() -> None:
        with pytest.raises(ClientDisconnect):
            await _disconnect_during_response_body(response)
        assert snapshots[0].closed is True

    assert len(snapshots) == 1
    asyncio.run(assert_disconnect_closes_snapshot())


def test_retry_restores_legacy_crop_asset_without_workspace_mutation(
    science_api_context,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    image = created.json()["source_image"]
    store = LocalAssetStore(context.asset_root)

    with context.session_factory.begin() as session:
        source_image = session.get(StructureSourceImage, image["id"])
        current_asset = session.get(Asset, image["crop_asset_id"])
        assert source_image is not None and current_asset is not None
        content = store.path_for(current_asset.storage_key).read_bytes()
        legacy_stored = store.put_bytes(content, suffix=".png")
        assert legacy_stored.storage_key.startswith("managed/objects/")
        legacy_asset = Asset(
            storage_key=legacy_stored.storage_key,
            original_filename=Path(legacy_stored.storage_key).name,
            sha256=legacy_stored.sha256,
            byte_size=legacy_stored.byte_size,
            mime_type="image/png",
            width=current_asset.width,
            height=current_asset.height,
            category=AssetCategory.EVIDENCE_CROP,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.MISSING,
            source_asset_id=current_asset.source_asset_id,
            derivation_metadata=dict(current_asset.derivation_metadata),
            source_metadata={},
            created_by_id=current_asset.created_by_id,
        )
        session.add(legacy_asset)
        session.flush()
        source_image.crop_asset_id = legacy_asset.id
        session.delete(current_asset)
        legacy_asset_id = legacy_asset.id
        legacy_path = legacy_stored.path
    legacy_path.unlink()

    retried = context.client.post(
        f"/api/v2/structure-source-images/{image['id']}/retry",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3},
    )

    assert retried.status_code == 200
    assert retried.json()["source_image"]["crop_asset_id"] == str(legacy_asset_id)
    assert retried.json()["workspace_version"] == 3
    assert legacy_path.is_file()
    assert legacy_path.read_bytes() == content
    with context.session_factory() as session:
        asset = session.get(Asset, legacy_asset_id)
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert asset is not None
        assert asset.integrity_state is AssetIntegrityState.VERIFIED
        assert workspace is not None and workspace.version == 3
        assert event_count == 2


@pytest.mark.parametrize(
    ("tamper", "expected_state"),
    [
        ("missing", AssetIntegrityState.MISSING),
        ("same_length_corrupt", AssetIntegrityState.CORRUPT),
    ],
)
def test_crop_content_integrity_failure_is_hidden_persisted_and_recoverable(
    science_api_context,
    tamper: str,
    expected_state: AssetIntegrityState,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    created = _create_image(context, csrf, compound["id"], version=2)
    assert created.status_code == 201
    image = created.json()["source_image"]
    asset_id = image["crop_asset_id"]
    with context.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        crop_path = LocalAssetStore(context.asset_root).path_for(asset.storage_key)
        original = crop_path.read_bytes()
    if tamper == "missing":
        crop_path.unlink()
    else:
        crop_path.write_bytes(bytes([original[0] ^ 0xFF]) + original[1:])
        assert crop_path.stat().st_size == len(original)

    hidden = context.client.get(
        f"/api/v2/structure-source-images/{image['id']}/content"
    )
    assert hidden.status_code == 404
    assert str(crop_path) not in hidden.text
    with context.session_factory() as session:
        asset = session.get(Asset, asset_id)
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert asset is not None and asset.integrity_state is expected_state
        assert workspace is not None and workspace.version == 3
        assert event_count == 2

    retried = context.client.post(
        f"/api/v2/structure-source-images/{image['id']}/retry",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3},
    )
    assert retried.status_code == 200
    assert retried.json()["source_image"]["crop_status"] == "ready"
    assert retried.json()["source_image"]["crop_asset_id"] == asset_id
    assert retried.json()["workspace_version"] == 3
    readable = context.client.get(
        f"/api/v2/structure-source-images/{image['id']}/content"
    )
    assert readable.status_code == 200
    assert readable.content == original
    with context.session_factory() as session:
        asset = session.get(Asset, asset_id)
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert asset is not None
        assert asset.integrity_state is AssetIntegrityState.VERIFIED
        assert asset.verified_at is not None
        assert workspace is not None and workspace.version == 3
        assert event_count == 2


def test_crop_renders_from_the_snapshot_that_passed_integrity_check(
    science_api_context,
    monkeypatch,
) -> None:
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    compound = _create_compound(context, csrf)
    source_root = Path(context.client.app.state.settings.source_roots["source_pdfs"])
    source_path = source_root / "volume67 issue5" / "science-11.pdf"
    trusted_copy = source_path.with_name("trusted-original.pdf")
    trusted_copy.write_bytes(source_path.read_bytes())
    replacement = source_path.with_name("replacement.pdf")
    document = pymupdf.open()
    for page_number in range(1, 4):
        page = document.new_page(width=320, height=240)
        page.insert_text((36, 48), f"REPLACEMENT page {page_number}")
        page.draw_rect(pymupdf.Rect(70, 80, 210, 180), color=(1, 0, 0), fill=(1, 0, 0))
    document.save(replacement)
    document.close()
    crop_request = CropRequest(
        source_pdf_sha256=_source_sha(context, context.first.paper_id),
        page_number=2,
        x0=0.2,
        y0=0.25,
        x1=0.7,
        y1=0.8,
        rotation=0,
        padding=0,
        dpi=144,
        renderer_version=PDF_RENDERER_VERSION,
    )
    expected_crop = render_pdf_crop(trusted_copy, crop_request)
    replacement_crop = render_pdf_crop(replacement, crop_request)
    assert expected_crop != replacement_crop

    real_open = Path.open
    replaced = False

    def replace_after_open(path: Path, *args, **kwargs):
        nonlocal replaced
        handle = real_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if path == source_path and not replaced and "r" in mode:
            replaced = True
            os.replace(replacement, source_path)
        return handle

    monkeypatch.setattr(Path, "open", replace_after_open)
    created = _create_image(context, csrf, compound["id"], version=2)
    assert replaced is True
    assert created.status_code == 201
    image = created.json()["source_image"]
    crop = context.client.get(
        f"/api/v2/structure-source-images/{image['id']}/content"
    )
    assert crop.status_code == 200
    assert crop.content == expected_crop
    assert crop.content != replacement_crop
