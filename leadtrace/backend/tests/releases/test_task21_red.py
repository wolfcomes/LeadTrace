from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from threading import Barrier, Lock, Thread
from types import SimpleNamespace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm.attributes import set_committed_value

from app.approvals.service import ApprovalConflict, ApprovalService
from app.activities.models import Activity
from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.compounds.models import Compound
from app.config import Settings
from app.database import (
    DatabaseResources,
    create_database_engine,
    create_session_factory,
)
from app.evidence.models import Evidence
from app.lineages.models import Lineage, LineageEdge
from app.main import create_app
from app.releases import export as release_export_module
from app.releases import service as release_service
from app.releases.export import (
    export_release,
    restore_release_export,
    verify_release_export,
)
from app.releases.manifest import (
    binding_base_hash,
    canonical_hash,
    capture_release_artifact_manifest,
    merge_binding_snapshots,
)
from app.releases.models import (
    Release,
    ReleaseArtifactManifest,
    ReleaseItem,
    ReleaseOperation,
)
from app.releases.router import PublishRequest, RollbackRequest
from app.releases.service import (
    ReleaseConflict,
    preview_approved_changeset,
    publish_approved_changeset,
    rollback_release,
)
from app.releases.validation import validate_release
from app.revisions.models import ObjectKind, ObjectRevision, RevisionedObject
from app.revisions.service import RevisionService
from app.revisions.service import canonical_snapshot_hash
from app.reviews.models import Changeset
from app.reviews.service import InvalidReview, ReviewService
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.visual_objects.models import (
    VisualObjectAssetBinding,
    VisualObject,
    VisualObjectCompoundBinding,
    VisualObjectRegionBinding,
    VisualObjectRelation,
    VisualRegion,
)
from app.visual_objects.bindings import BindingConflict, BindingService, ObjectRelationType
from app.visual_objects.relationships import RelationshipService
from tests.reviews.test_service import PASSWORD as REVIEW_PASSWORD
from tests.reviews.test_service import _add_paper_item, _setup


def test_task21_release_helpers_are_available() -> None:
    assert callable(validate_release)
    assert callable(export_release)


def test_http_release_requests_do_not_expose_failure_injection() -> None:
    assert "fail_stage" not in PublishRequest.model_json_schema()["properties"]
    assert "fail_stage" not in RollbackRequest.model_json_schema()["properties"]


def test_release_export_scalar_helpers_handle_nested_values_without_type_errors() -> None:
    nested = ["not-a-scalar"]

    assert release_export_module._snapshot_value(
        {"normalized_values": {"compound_id": nested}},
        "compound_id",
    ) == nested
    with pytest.raises(ValueError, match="not a UUID"):
        release_export_module._optional_uuid(nested)


def _resign_export(payload: dict[str, object]) -> dict[str, object]:
    unsigned = deepcopy(payload)
    unsigned.pop("sha256_manifest", None)
    canonical = json.dumps(
        release_export_module._stable(unsigned),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=release_export_module._json_default,
    ).encode("utf-8")
    payload["sha256_manifest"] = {
        "payload": hashlib.sha256(canonical).hexdigest()
    }
    return payload


def _approved_changeset(session):
    reviewer, _, admin, paper, paper_revision, release = _setup(session)
    capture_release_artifact_manifest(session, release.id)
    review = ReviewService()
    task = review.create_task(
        session,
        paper_id=paper.id,
        assignee_id=reviewer.id,
        created_by_id=admin.id,
    )
    changeset = review.create_changeset(
        session,
        paper_id=paper.id,
        actor_id=reviewer.id,
        review_task_id=task.id,
        base_release_id=release.id,
        title="Publish reviewed Paper",
        reason="Task 21 release test",
    )
    item = _add_paper_item(session, review, changeset, reviewer, paper, paper_revision)
    review.update_changeset_item(
        session,
        changeset_id=changeset.id,
        item_id=item.id,
        actor_id=reviewer.id,
        expected_version=2,
        proposed_snapshot={"paper_key": paper.paper_key, "reviewed": True},
    )
    review.submit_changeset(
        session,
        changeset_id=changeset.id,
        actor_id=reviewer.id,
        expected_version=3,
    )
    approved = ApprovalService().approve(
        session,
        changeset_id=changeset.id,
        actor_id=admin.id,
        expected_version=4,
        reason="Validated by an independent Admin",
    )
    return reviewer, admin, paper, release, changeset, approved


def _append_published_item(
    session,
    *,
    release: Release,
    identity: RevisionedObject,
    actor_id,
    paper_id,
    snapshot: dict[str, object],
    order: int,
) -> ObjectRevision:
    revision = RevisionService().create_revision(
        session,
        object_identity=identity,
        actor_id=actor_id,
        reason="Build release validation fixture",
        snapshot=snapshot,
        workflow_state=WorkflowState.PUBLISHED,
        is_current_published=True,
    )
    session.add(
        ReleaseItem(
            release_id=release.id,
            object_id=identity.id,
            revision_id=revision.id,
            paper_id=paper_id,
            object_kind=identity.object_kind,
            manifest_order=order,
        )
    )
    session.flush()
    return revision


def _add_visual_release_content(
    session,
    *,
    release: Release,
    admin_id,
    paper_id,
    legacy_binding_schema: bool = False,
) -> dict[str, object]:
    drawing = Asset(
        storage_key=f"managed/structures/{uuid4().hex}.png",
        original_filename="restored-structure.png",
        sha256="b" * 64,
        byte_size=256,
        mime_type="image/png",
        width=640,
        height=480,
        category=AssetCategory.RDKIT_STRUCTURE,
        access_level=AssetAccessLevel.VISITOR,
        integrity_state=AssetIntegrityState.VERIFIED,
        derivation_metadata={"renderer": "rdkit"},
        source_metadata={"source": "task21-test"},
        created_by_id=admin_id,
    )
    compound = Compound(
        paper_id=paper_id,
        local_identity="restore-compound-7a",
        display_label="7a",
        normalized_label="7a",
    )
    session.add_all([drawing, compound])
    session.flush()
    structure = Structure(
        paper_id=paper_id,
        compound_id=compound.id,
        structure_key="restore-structure-7a",
    )
    region = VisualRegion(
        paper_id=paper_id,
        region_key="restore-region-7a",
        asset_id=drawing.id,
        page_number=2,
    )
    visual_object = VisualObject(
        paper_id=paper_id,
        object_key="restore-visual-7a",
        object_type="complete_molecule",
    )
    session.add_all([structure, region, visual_object])
    session.flush()
    _append_published_item(
        session,
        release=release,
        identity=compound,
        actor_id=admin_id,
        paper_id=paper_id,
        snapshot={
            "local_identity": compound.local_identity,
            "display_label": compound.display_label,
            "normalized_label": compound.normalized_label,
        },
        order=2,
    )
    _append_published_item(
        session,
        release=release,
        identity=structure,
        actor_id=admin_id,
        paper_id=paper_id,
        snapshot={
            "structure_key": structure.structure_key,
            "compound_id": str(compound.id),
            "canonical_smiles": "CCO",
            "structure_state": "structure_confirmed",
            "drawing_asset_id": str(drawing.id),
        },
        order=3,
    )
    _append_published_item(
        session,
        release=release,
        identity=region,
        actor_id=admin_id,
        paper_id=paper_id,
        snapshot={
            "region_key": region.region_key,
            "page_number": region.page_number,
            "x0": 0.1,
            "y0": 0.2,
            "x1": 0.7,
            "y1": 0.8,
        },
        order=4,
    )
    _append_published_item(
        session,
        release=release,
        identity=visual_object,
        actor_id=admin_id,
        paper_id=paper_id,
        snapshot={
            "object_key": visual_object.object_key,
            "object_type": str(visual_object.object_type),
        },
        order=5,
    )
    region_binding_id = uuid4()
    compound_binding_id = uuid4()
    if legacy_binding_schema:
        session.execute(
            text(
                """
                INSERT INTO visual_object_region_bindings (
                    id, visual_object_id, region_id, role, note
                ) VALUES (
                    :id, :visual_object_id, :region_id, 'source', 'Published source crop'
                )
                """
            ),
            {
                "id": region_binding_id,
                "visual_object_id": visual_object.id,
                "region_id": region.id,
            },
        )
        session.execute(
            text(
                """
                INSERT INTO visual_object_compound_bindings (
                    id, visual_object_id, compound_id, label, role,
                    confidence, note, is_primary
                ) VALUES (
                    :id, :visual_object_id, :compound_id, '7a', 'label',
                    0.99, NULL, true
                )
                """
            ),
            {
                "id": compound_binding_id,
                "visual_object_id": visual_object.id,
                "compound_id": compound.id,
            },
        )
    else:
        session.add_all(
            [
                VisualObjectRegionBinding(
                    id=region_binding_id,
                    visual_object_id=visual_object.id,
                    region_id=region.id,
                    logical_key=f"region:{visual_object.id}:{region.id}",
                    role="source",
                    note="Published source crop",
                ),
                VisualObjectCompoundBinding(
                    id=compound_binding_id,
                    visual_object_id=visual_object.id,
                    compound_id=compound.id,
                    label="7a",
                    logical_key=(
                        f"compound:{visual_object.id}:{compound.id}:7a"
                    ),
                    role="label",
                    confidence=0.99,
                    is_primary=True,
                ),
            ]
        )
    release.manifest_finalized = True
    session.flush()
    if not legacy_binding_schema:
        capture_release_artifact_manifest(session, release.id)
    return {
        "asset_id": drawing.id,
        "compound_id": compound.id,
        "structure_id": structure.id,
        "region_id": region.id,
        "region_binding_id": region_binding_id,
        "visual_object_id": visual_object.id,
        "compound_binding_id": compound_binding_id,
    }


def _visual_release_export_fixture(session) -> dict[str, object]:
    _, _, admin, paper, _, release = _setup(session, finalize_release=False)
    _add_visual_release_content(
        session,
        release=release,
        admin_id=admin.id,
        paper_id=paper.id,
    )
    return export_release(session, release.id)


def test_restore_rejects_resigned_revision_snapshot_tampering(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        payload = _visual_release_export_fixture(session)
        tampered = deepcopy(payload)
        revision = tampered["revisions"][0]
        snapshot = {**revision["snapshot"], "tampered": True}
        revision["snapshot"] = snapshot
        revision["revision"]["snapshot"] = snapshot
        section = {
            "paper": "papers",
            "compound": "compounds",
            "structure": "structures",
            "lineage": "lineages",
            "lineage_edge": "lineage_edges",
            "evidence": "evidence",
            "activity": "activities",
            "visual_region": "regions",
            "visual_object": "visual_objects",
        }[revision["object_kind"]]
        next(row for row in tampered[section] if row["id"] == revision["object_id"])[
            "snapshot"
        ] = snapshot
        _resign_export(tampered)

        with pytest.raises(ValueError, match="revision content hash"):
            restore_release_export(session, tampered)


def test_restore_rejects_resigned_artifact_snapshot_tampering(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        payload = _visual_release_export_fixture(session)
        tampered = deepcopy(payload)
        tampered["artifact_manifest"]["snapshot"]["capture_mode"] = "forged"
        _resign_export(tampered)

        with pytest.raises(ValueError, match="artifact content hash"):
            restore_release_export(session, tampered)


def test_restore_rejects_asset_manifest_that_differs_from_frozen_artifact(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        payload = _visual_release_export_fixture(session)
        tampered = deepcopy(payload)
        tampered["asset_manifest"][0]["storage_key"] = "managed/forged.png"
        _resign_export(tampered)

        with pytest.raises(ValueError, match="asset manifest"):
            restore_release_export(session, tampered)


def test_restore_rejects_asset_release_without_physical_store(
    auth_session_factory,
    postgresql_database_url,
) -> None:
    with auth_session_factory.begin() as session:
        payload = _visual_release_export_fixture(session)
    schema = f"restore_without_store_{uuid4().hex}"
    source_engine = auth_session_factory.kw["bind"]
    with source_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    disposable_url = make_url(postgresql_database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        disposable_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    config.attributes["leadtrace_database_url"] = disposable_url.render_as_string(
        hide_password=False
    )
    config.attributes["leadtrace_expected_database_name"] = make_url(
        postgresql_database_url
    ).database
    command.upgrade(config, "head")
    disposable_engine = create_database_engine(
        disposable_url.render_as_string(hide_password=False)
    )
    try:
        with create_session_factory(disposable_engine).begin() as session:
            with pytest.raises(ValueError, match="asset store"):
                restore_release_export(session, payload)
    finally:
        disposable_engine.dispose()
        with source_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_restore_rejects_resigned_dangling_scientific_reference(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        payload = _visual_release_export_fixture(session)
        tampered = deepcopy(payload)
        revision = next(
            row for row in tampered["revisions"] if row["object_kind"] == "structure"
        )
        snapshot = {**revision["snapshot"], "compound_id": str(uuid4())}
        revision["snapshot"] = snapshot
        revision["revision"]["snapshot"] = snapshot
        revision["revision"]["content_hash"] = canonical_snapshot_hash(snapshot)
        structure = next(
            row for row in tampered["structures"] if row["id"] == revision["object_id"]
        )
        structure["snapshot"] = snapshot
        _resign_export(tampered)

        with pytest.raises(ValueError, match="reference closure"):
            restore_release_export(session, tampered)


def test_release_validation_rejects_live_asset_metadata_drift(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, _, admin, paper, _, release = _setup(session, finalize_release=False)
        fixture = _add_visual_release_content(
            session,
            release=release,
            admin_id=admin.id,
            paper_id=paper.id,
        )
        asset = session.get(Asset, fixture["asset_id"])
        assert asset is not None
        asset.storage_key = "managed/structures/moved-after-release.png"
        asset.sha256 = "d" * 64
        asset.byte_size += 1
        session.flush([asset])

        validation = validate_release(session, release.id)

        assert validation.valid is False
        assert any(issue.code == "asset_manifest_mismatch" for issue in validation.issues)


def _binding_release_fixture(session, *, include_base_bindings: bool = False):
    reviewer, other, admin, paper, paper_revision, release = _setup(
        session,
        finalize_release=False,
    )
    asset = Asset(
        storage_key=f"managed/objects/{uuid4().hex}.png",
        original_filename="binding-source.png",
        sha256="c" * 64,
        byte_size=512,
        mime_type="image/png",
        category=AssetCategory.EVIDENCE_CROP,
        access_level=AssetAccessLevel.REVIEWER,
        integrity_state=AssetIntegrityState.VERIFIED,
        derivation_metadata={},
        source_metadata={"source": "task21-binding-test"},
        created_by_id=admin.id,
    )
    compound = Compound(
        paper_id=paper.id,
        local_identity=f"binding-compound-{uuid4().hex[:8]}",
        display_label="Binding compound",
        normalized_label="binding compound",
    )
    region = VisualRegion(
        paper_id=paper.id,
        region_key=f"binding-region-{uuid4().hex[:8]}",
        asset_id=asset.id,
        page_number=1,
    )
    source_object = VisualObject(
        paper_id=paper.id,
        object_key=f"binding-source-{uuid4().hex[:8]}",
        object_type="complete_molecule",
    )
    target_object = VisualObject(
        paper_id=paper.id,
        object_key=f"binding-target-{uuid4().hex[:8]}",
        object_type="r_group",
    )
    session.add_all([asset, compound, region, source_object, target_object])
    session.flush()
    fixtures = (
        (
            compound,
            {
                "local_identity": compound.local_identity,
                "display_label": compound.display_label,
            },
        ),
        (
            region,
            {
                "region_key": region.region_key,
                "asset_id": str(asset.id),
                "page_number": region.page_number,
                "bounds": {"x0": 0.1, "y0": 0.1, "x1": 0.8, "y1": 0.8},
                "rotation": 0,
            },
        ),
        (
            source_object,
            {
                "object_key": source_object.object_key,
                "object_type": str(source_object.object_type),
            },
        ),
        (
            target_object,
            {
                "object_key": target_object.object_key,
                "object_type": str(target_object.object_type),
            },
        ),
    )
    for order, (identity, snapshot) in enumerate(fixtures, start=2):
        _append_published_item(
            session,
            release=release,
            identity=identity,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot=snapshot,
            order=order,
        )
    base_bindings = {}
    if include_base_bindings:
        base_bindings = {
            "region": VisualObjectRegionBinding(
                visual_object_id=source_object.id,
                region_id=region.id,
                operation="add",
                logical_key=f"region:{source_object.id}:{region.id}",
                role="source",
                note="Frozen Region binding",
            ),
            "asset": VisualObjectAssetBinding(
                visual_object_id=source_object.id,
                asset_id=asset.id,
                operation="add",
                logical_key=f"asset:{source_object.id}:{asset.id}",
                role="image",
                is_primary=True,
            ),
            "compound": VisualObjectCompoundBinding(
                visual_object_id=source_object.id,
                compound_id=compound.id,
                operation="add",
                logical_key=(
                    f"compound:{source_object.id}:{compound.id}:Frozen label"
                ),
                label="Frozen label",
                role="label",
                confidence=0.95,
                note="Frozen compound binding",
                is_primary=True,
            ),
            "relation": VisualObjectRelation(
                source_object_id=source_object.id,
                target_object_id=target_object.id,
                operation="add",
                logical_key=(
                    f"relation:{source_object.id}:{target_object.id}:substituent_of"
                ),
                relation_type="substituent_of",
                note="Frozen relation",
            ),
        }
        session.add_all(base_bindings.values())
        session.flush()
    release.manifest_finalized = True
    session.flush([release])
    capture_release_artifact_manifest(session, release.id)
    return {
        "reviewer": reviewer,
        "other": other,
        "admin": admin,
        "paper": paper,
        "paper_revision": paper_revision,
        "release": release,
        "asset": asset,
        "compound": compound,
        "region": region,
        "source_object": source_object,
        "target_object": target_object,
        "base_bindings": base_bindings,
    }


def _paper_changeset(session, fixture, reviewer, *, title: str):
    review = ReviewService()
    task = review.create_task(
        session,
        paper_id=fixture["paper"].id,
        assignee_id=reviewer.id,
        created_by_id=fixture["admin"].id,
    )
    changeset = review.create_changeset(
        session,
        paper_id=fixture["paper"].id,
        actor_id=reviewer.id,
        review_task_id=task.id,
        base_release_id=fixture["release"].id,
        title=title,
        reason="Exercise approval-scoped visual bindings",
    )
    item = _add_paper_item(
        session,
        review,
        changeset,
        reviewer,
        fixture["paper"],
        fixture["paper_revision"],
    )
    review.update_changeset_item(
        session,
        changeset_id=changeset.id,
        item_id=item.id,
        actor_id=reviewer.id,
        expected_version=changeset.version,
        proposed_snapshot={
            "paper_key": fixture["paper"].paper_key,
            "binding_test": title,
        },
    )
    return changeset


def _add_all_binding_deltas(session, fixture, changeset) -> None:
    service = BindingService()
    service.bind_region(
        session,
        object_id=fixture["source_object"].id,
        region_id=fixture["region"].id,
        changeset_id=changeset.id,
        actor_id=changeset.owner_id,
        expected_version=changeset.version,
    )
    service.bind_asset(
        session,
        object_id=fixture["source_object"].id,
        asset_id=fixture["asset"].id,
        changeset_id=changeset.id,
        actor_id=changeset.owner_id,
        expected_version=changeset.version,
        is_primary=True,
    )
    service.bind_compound(
        session,
        object_id=fixture["source_object"].id,
        compound_id=fixture["compound"].id,
        label="Binding compound",
        changeset_id=changeset.id,
        actor_id=changeset.owner_id,
        expected_version=changeset.version,
        is_primary=True,
    )
    RelationshipService().create_relation(
        session,
        source_object_id=fixture["source_object"].id,
        target_object_id=fixture["target_object"].id,
        relation_type=ObjectRelationType.SUBSTITUENT_OF,
        changeset_id=changeset.id,
        actor_id=changeset.owner_id,
        expected_version=changeset.version,
    )


def _submit_and_approve(session, fixture, reviewer, changeset) -> None:
    ReviewService().submit_changeset(
        session,
        changeset_id=changeset.id,
        actor_id=reviewer.id,
        expected_version=changeset.version,
    )
    ApprovalService().approve(
        session,
        changeset_id=changeset.id,
        actor_id=fixture["admin"].id,
        expected_version=changeset.version,
        reason="Approve the complete visual binding delta",
    )


def test_unapproved_visual_binding_deltas_do_not_leak_into_another_release(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        draft = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Unapproved binding draft",
        )
        _add_all_binding_deltas(session, fixture, draft)
        approved = _paper_changeset(
            session,
            fixture,
            fixture["other"],
            title="Independent approved change",
        )
        _submit_and_approve(session, fixture, fixture["other"], approved)

        published = publish_approved_changeset(
            session,
            changeset_id=approved.id,
            actor_id=fixture["admin"].id,
            idempotency_key="exclude-unapproved-bindings",
        ).release
        artifact = session.get(ReleaseArtifactManifest, published.id)

        assert artifact is not None
        assert artifact.snapshot["bindings"] == {
            "visual_object_regions": [],
            "visual_object_assets": [],
            "visual_object_compounds": [],
            "visual_object_relations": [],
        }


def test_same_binding_can_be_proposed_in_independent_changesets(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        first = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="First isolated binding draft",
        )
        second = _paper_changeset(
            session,
            fixture,
            fixture["other"],
            title="Second isolated binding draft",
        )
        service = BindingService()
        service.bind_region(
            session,
            object_id=fixture["source_object"].id,
            region_id=fixture["region"].id,
            changeset_id=first.id,
            actor_id=first.owner_id,
            expected_version=first.version,
        )
        service.bind_region(
            session,
            object_id=fixture["source_object"].id,
            region_id=fixture["region"].id,
            changeset_id=second.id,
            actor_id=second.owner_id,
            expected_version=second.version,
        )


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_binding_routes_hide_another_reviewer_changeset_for_every_mutation(
    method: str,
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Attacker paper access",
        )
        victim = _paper_changeset(
            session,
            fixture,
            fixture["other"],
            title=f"Victim binding {method}",
        )
        binding_id = uuid4()
        if method != "POST":
            session.add(
                VisualObjectRegionBinding(
                    id=binding_id,
                    visual_object_id=fixture["source_object"].id,
                    region_id=fixture["region"].id,
                    changeset_id=victim.id,
                    operation="add",
                    logical_key=(
                        f"region:{fixture['source_object'].id}:"
                        f"{fixture['region'].id}"
                    ),
                    role="source",
                )
            )
            session.flush()
        paper_id = fixture["paper"].id
        object_id = fixture["source_object"].id
        region_id = fixture["region"].id
        victim_id = victim.id
        victim_version = victim.version
        attacker_username = fixture["reviewer"].username

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="binding-route-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": attacker_username, "password": REVIEW_PASSWORD},
        )
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        path = f"/api/v1/papers/{paper_id}/visual-objects/{object_id}/regions"
        if method != "POST":
            path = f"{path}/{binding_id}"
        payload = {
            "changeset_id": str(victim_id),
            "expected_version": victim_version,
        }
        if method == "POST":
            payload.update({"region_id": str(region_id), "role": "source"})
        elif method == "PATCH":
            payload.update({"role": "reviewed", "note": "cross-review edit"})
        response = client.request(method, path, headers=headers, json=payload)

    assert response.status_code == 404


@pytest.mark.parametrize(
    "binding_kind",
    ["region", "asset", "compound", "relation"],
)
def test_binding_creation_rejects_logical_keys_in_the_frozen_base(
    binding_kind: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title=f"Duplicate frozen {binding_kind}",
        )
        service = BindingService()

        with pytest.raises(BindingConflict, match="frozen base release"):
            if binding_kind == "region":
                service.bind_region(
                    session,
                    object_id=fixture["source_object"].id,
                    region_id=fixture["region"].id,
                    changeset_id=changeset.id,
                    actor_id=changeset.owner_id,
                    expected_version=changeset.version,
                )
            elif binding_kind == "asset":
                service.bind_asset(
                    session,
                    object_id=fixture["source_object"].id,
                    asset_id=fixture["asset"].id,
                    changeset_id=changeset.id,
                    actor_id=changeset.owner_id,
                    expected_version=changeset.version,
                )
            elif binding_kind == "compound":
                service.bind_compound(
                    session,
                    object_id=fixture["source_object"].id,
                    compound_id=fixture["compound"].id,
                    label="Frozen label",
                    changeset_id=changeset.id,
                    actor_id=changeset.owner_id,
                    expected_version=changeset.version,
                )
            else:
                RelationshipService().create_relation(
                    session,
                    source_object_id=fixture["source_object"].id,
                    target_object_id=fixture["target_object"].id,
                    relation_type=ObjectRelationType.SUBSTITUENT_OF,
                    changeset_id=changeset.id,
                    actor_id=changeset.owner_id,
                    expected_version=changeset.version,
                )


def test_submission_rejects_malformed_binding_rows_inserted_below_the_service(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Malformed binding submission",
        )
        session.add(
            VisualObjectRegionBinding(
                visual_object_id=fixture["source_object"].id,
                region_id=fixture["region"].id,
                changeset_id=changeset.id,
                operation="add",
                logical_key=(
                    f"region:{fixture['source_object'].id}:{fixture['region'].id}"
                ),
                role="source",
            )
        )
        session.flush()

        with pytest.raises(InvalidReview, match="Binding delta"):
            ReviewService().submit_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=fixture["reviewer"].id,
                expected_version=changeset.version,
            )


def _binding_logical_key_for_fixture(fixture, binding_kind: str) -> str:
    if binding_kind == "region":
        return f"region:{fixture['source_object'].id}:{fixture['region'].id}"
    if binding_kind == "asset":
        return f"asset:{fixture['source_object'].id}:{fixture['asset'].id}"
    if binding_kind == "compound":
        return (
            f"compound:{fixture['source_object'].id}:"
            f"{fixture['compound'].id}:Frozen label"
        )
    return (
        f"relation:{fixture['source_object'].id}:"
        f"{fixture['target_object'].id}:substituent_of"
    )


def _draft_binding_record(fixture, changeset: Changeset, binding_kind: str, key: str):
    if binding_kind == "region":
        return VisualObjectRegionBinding(
            visual_object_id=fixture["source_object"].id,
            region_id=fixture["region"].id,
            changeset_id=changeset.id,
            operation="add",
            logical_key=key,
            role="source",
        )
    if binding_kind == "asset":
        return VisualObjectAssetBinding(
            visual_object_id=fixture["source_object"].id,
            asset_id=fixture["asset"].id,
            changeset_id=changeset.id,
            operation="add",
            logical_key=key,
            role="image",
            is_primary=False,
        )
    if binding_kind == "compound":
        return VisualObjectCompoundBinding(
            visual_object_id=fixture["source_object"].id,
            compound_id=fixture["compound"].id,
            changeset_id=changeset.id,
            operation="add",
            logical_key=key,
            label="Frozen label",
            role="label",
            is_primary=False,
        )
    return VisualObjectRelation(
        source_object_id=fixture["source_object"].id,
        target_object_id=fixture["target_object"].id,
        changeset_id=changeset.id,
        operation="add",
        logical_key=key,
        relation_type="substituent_of",
    )


@pytest.mark.parametrize("binding_kind", ["region", "asset", "compound", "relation"])
def test_submission_rejects_forged_binding_logical_keys(
    auth_session_factory,
    binding_kind: str,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title=f"Forged {binding_kind} logical key",
        )
        forged_key = f"{_binding_logical_key_for_fixture(fixture, binding_kind)}:forged"
        session.add(_draft_binding_record(fixture, changeset, binding_kind, forged_key))
        session.flush()

        with pytest.raises(InvalidReview, match="Binding delta"):
            ReviewService().submit_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=fixture["reviewer"].id,
                expected_version=changeset.version,
            )


@pytest.mark.parametrize("binding_kind", ["region", "asset", "compound", "relation"])
def test_submission_rejects_empty_persisted_binding_logical_keys(
    auth_session_factory,
    binding_kind: str,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title=f"Empty {binding_kind} logical key",
        )
        session.add(_draft_binding_record(fixture, changeset, binding_kind, ""))
        session.flush()

        with pytest.raises(InvalidReview, match="Binding delta"):
            ReviewService().submit_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=fixture["reviewer"].id,
                expected_version=changeset.version,
            )


@pytest.mark.parametrize("binding_kind", ["region", "asset", "compound", "relation"])
def test_submission_rejects_conflicting_duplicate_binding_deltas(
    auth_session_factory,
    binding_kind: str,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title=f"Duplicate {binding_kind} binding delta",
        )
        canonical_key = _binding_logical_key_for_fixture(fixture, binding_kind)
        session.add_all(
            [
                _draft_binding_record(fixture, changeset, binding_kind, canonical_key),
                _draft_binding_record(fixture, changeset, binding_kind, ""),
            ]
        )
        session.flush()

        with pytest.raises(InvalidReview, match="Binding delta"):
            ReviewService().submit_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=fixture["reviewer"].id,
                expected_version=changeset.version,
            )


@pytest.mark.parametrize("binding_kind", ["region", "asset", "compound", "relation"])
def test_approval_rejects_conflicting_duplicate_binding_deltas(
    auth_session_factory,
    binding_kind: str,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title=f"Conflicting {binding_kind} approval delta",
        )
        ReviewService().submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=fixture["reviewer"].id,
            expected_version=changeset.version,
        )
        artifact = session.get(ReleaseArtifactManifest, fixture["release"].id)
        assert artifact is not None
        collection_by_kind = {
            "region": "visual_object_regions",
            "asset": "visual_object_assets",
            "compound": "visual_object_compounds",
            "relation": "visual_object_relations",
        }
        collection = collection_by_kind[binding_kind]
        base_row = artifact.snapshot["bindings"][collection][0]
        update_row = {
            **base_row,
            "id": str(uuid4()),
            "changeset_id": str(changeset.id),
            "operation": "update",
            "base_hash": binding_base_hash(base_row),
        }
        remove_row = {
            **update_row,
            "id": str(uuid4()),
            "operation": "remove",
        }
        remove_row.pop("logical_key")
        malformed_snapshot = deepcopy(changeset.submitted_snapshot)
        malformed_snapshot["binding_delta"][collection] = [update_row, remove_row]
        set_committed_value(changeset, "submitted_snapshot", malformed_snapshot)

        with pytest.raises(ApprovalConflict, match="Binding delta"):
            ApprovalService().approve(
                session,
                changeset_id=changeset.id,
                actor_id=fixture["admin"].id,
                expected_version=changeset.version,
                reason="Conflicting binding delta identities cannot be approved",
            )


def _inject_mismatched_binding_endpoint(
    changeset: Changeset,
    artifact: ReleaseArtifactManifest,
    binding_kind: str,
    operation: str,
) -> None:
    collection_by_kind = {
        "region": "visual_object_regions",
        "asset": "visual_object_assets",
        "compound": "visual_object_compounds",
        "relation": "visual_object_relations",
    }
    endpoint_by_kind = {
        "region": "region_id",
        "asset": "asset_id",
        "compound": "compound_id",
        "relation": "target_object_id",
    }
    collection = collection_by_kind[binding_kind]
    base_row = artifact.snapshot["bindings"][collection][0]
    malformed_snapshot = deepcopy(changeset.submitted_snapshot)
    malformed_row = {
        **base_row,
        "id": str(uuid4()),
        "changeset_id": str(changeset.id),
        "operation": operation,
        "base_hash": binding_base_hash(base_row),
        endpoint_by_kind[binding_kind]: str(uuid4()),
    }
    malformed_snapshot["binding_delta"][collection] = [malformed_row]
    set_committed_value(changeset, "submitted_snapshot", malformed_snapshot)


@pytest.mark.parametrize("binding_kind", ["region", "asset", "compound", "relation"])
def test_approval_rejects_binding_updates_with_mismatched_endpoints(
    auth_session_factory,
    binding_kind: str,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title=f"Mismatched {binding_kind} update",
        )
        ReviewService().submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=fixture["reviewer"].id,
            expected_version=changeset.version,
        )
        artifact = session.get(ReleaseArtifactManifest, fixture["release"].id)
        assert artifact is not None
        _inject_mismatched_binding_endpoint(
            changeset,
            artifact,
            binding_kind,
            "update",
        )

        with pytest.raises(ApprovalConflict, match="Binding delta"):
            ApprovalService().approve(
                session,
                changeset_id=changeset.id,
                actor_id=fixture["admin"].id,
                expected_version=changeset.version,
                reason="Binding update identity must match the frozen base",
            )


@pytest.mark.parametrize("binding_kind", ["region", "asset", "compound", "relation"])
def test_approval_rejects_binding_removals_with_mismatched_endpoints(
    auth_session_factory,
    binding_kind: str,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title=f"Mismatched {binding_kind} removal",
        )
        ReviewService().submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=fixture["reviewer"].id,
            expected_version=changeset.version,
        )
        artifact = session.get(ReleaseArtifactManifest, fixture["release"].id)
        assert artifact is not None
        _inject_mismatched_binding_endpoint(
            changeset,
            artifact,
            binding_kind,
            "remove",
        )

        with pytest.raises(ApprovalConflict, match="Binding delta"):
            ApprovalService().approve(
                session,
                changeset_id=changeset.id,
                actor_id=fixture["admin"].id,
                expected_version=changeset.version,
                reason="Binding removal identity must match the frozen base",
            )


def test_approval_revalidates_the_frozen_binding_delta(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Malformed binding approval",
        )
        ReviewService().submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=fixture["reviewer"].id,
            expected_version=changeset.version,
        )
        artifact = session.get(ReleaseArtifactManifest, fixture["release"].id)
        assert artifact is not None
        base_row = artifact.snapshot["bindings"]["visual_object_regions"][0]
        malformed_snapshot = deepcopy(changeset.submitted_snapshot)
        malformed_snapshot["binding_delta"]["visual_object_regions"] = [
            {
                **base_row,
                "id": str(uuid4()),
                "changeset_id": str(changeset.id),
                "operation": "add",
                "base_hash": None,
            }
        ]
        set_committed_value(changeset, "submitted_snapshot", malformed_snapshot)

        with pytest.raises(ApprovalConflict, match="Binding delta"):
            ApprovalService().approve(
                session,
                changeset_id=changeset.id,
                actor_id=fixture["admin"].id,
                expected_version=changeset.version,
                reason="Malformed binding deltas cannot be approved",
            )


def test_binding_delta_can_update_and_remove_a_base_logical_binding() -> None:
    base_row = {
        "id": "base-binding",
        "visual_object_id": "object-1",
        "region_id": "region-1",
        "logical_key": "region:object-1:region-1",
        "operation": "add",
        "role": "source",
        "note": "old",
    }
    updated = {
        **base_row,
        "id": "draft-binding",
        "changeset_id": "changeset-1",
        "operation": "update",
        "base_hash": binding_base_hash(base_row),
        "role": "primary",
        "note": "reviewed",
    }
    merged = merge_binding_snapshots(
        {"visual_object_regions": [base_row]},
        {"visual_object_regions": [updated]},
    )
    assert merged["visual_object_regions"] == [updated]

    removed = {**updated, "operation": "remove"}
    assert merge_binding_snapshots(
        {"visual_object_regions": [base_row]},
        {"visual_object_regions": [removed]},
    )["visual_object_regions"] == []


@pytest.mark.parametrize(
    ("operation", "include_base", "base_hash"),
    [
        ("add", True, None),
        ("add", False, "unexpected-base-hash"),
        ("add", True, "unexpected-base-hash"),
        ("update", False, None),
        ("update", False, "orphan-base-hash"),
        ("update", True, None),
        ("update", True, "wrong-base-hash"),
        ("remove", False, None),
        ("remove", False, "orphan-base-hash"),
        ("remove", True, None),
        ("remove", True, "wrong-base-hash"),
        ("replace", True, None),
    ],
)
def test_binding_delta_rejects_invalid_state_transitions(
    operation: str,
    include_base: bool,
    base_hash: str | None,
) -> None:
    base_row = {
        "id": "base-binding",
        "visual_object_id": "object-1",
        "region_id": "region-1",
        "logical_key": "region:object-1:region-1",
        "operation": "add",
        "role": "source",
    }
    delta_row = {
        **base_row,
        "id": "draft-binding",
        "changeset_id": "changeset-1",
        "operation": operation,
        "role": "reviewed",
    }
    if base_hash is not None:
        delta_row["base_hash"] = base_hash

    with pytest.raises(ValueError, match="Binding delta"):
        merge_binding_snapshots(
            {"visual_object_regions": [base_row] if include_base else []},
            {"visual_object_regions": [delta_row]},
        )


def test_binding_mutations_reject_sources_owned_by_another_draft(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        owner_changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Binding source draft",
        )
        target_changeset = _paper_changeset(
            session,
            fixture,
            fixture["other"],
            title="Unrelated binding target draft",
        )
        binding_service = BindingService()
        region = binding_service.bind_region(
            session,
            object_id=fixture["source_object"].id,
            region_id=fixture["region"].id,
            changeset_id=owner_changeset.id,
            actor_id=owner_changeset.owner_id,
            expected_version=owner_changeset.version,
        )
        asset = binding_service.bind_asset(
            session,
            object_id=fixture["source_object"].id,
            asset_id=fixture["asset"].id,
            changeset_id=owner_changeset.id,
            actor_id=owner_changeset.owner_id,
            expected_version=owner_changeset.version,
        )
        compound = binding_service.bind_compound(
            session,
            object_id=fixture["source_object"].id,
            compound_id=fixture["compound"].id,
            label="Cross-draft label",
            changeset_id=owner_changeset.id,
            actor_id=owner_changeset.owner_id,
            expected_version=owner_changeset.version,
        )
        relation = RelationshipService().create_relation(
            session,
            source_object_id=fixture["source_object"].id,
            target_object_id=fixture["target_object"].id,
            relation_type=ObjectRelationType.SUBSTITUENT_OF,
            changeset_id=owner_changeset.id,
            actor_id=owner_changeset.owner_id,
            expected_version=owner_changeset.version,
        )
        update_calls = [
            lambda: binding_service.update_region(
                session,
                binding_id=region.id,
                changeset_id=target_changeset.id,
                actor_id=target_changeset.owner_id,
                expected_version=target_changeset.version,
                role="reviewed",
                note=None,
            ),
            lambda: binding_service.update_asset(
                session,
                binding_id=asset.id,
                changeset_id=target_changeset.id,
                actor_id=target_changeset.owner_id,
                expected_version=target_changeset.version,
                role="reviewed",
                is_primary=False,
            ),
            lambda: binding_service.update_compound(
                session,
                binding_id=compound.id,
                changeset_id=target_changeset.id,
                actor_id=target_changeset.owner_id,
                expected_version=target_changeset.version,
                label="Updated label",
                role="reviewed",
                confidence=0.9,
                note=None,
                is_primary=False,
                label_bbox=None,
            ),
            lambda: RelationshipService().update_relation(
                session,
                relation_id=relation.id,
                changeset_id=target_changeset.id,
                actor_id=target_changeset.owner_id,
                expected_version=target_changeset.version,
                note="reviewed",
            ),
        ]
        remove_calls = [
            lambda: binding_service.remove_region(
                session,
                binding_id=region.id,
                changeset_id=target_changeset.id,
                actor_id=target_changeset.owner_id,
                expected_version=target_changeset.version,
            ),
            lambda: binding_service.remove_asset(
                session,
                binding_id=asset.id,
                changeset_id=target_changeset.id,
                actor_id=target_changeset.owner_id,
                expected_version=target_changeset.version,
            ),
            lambda: binding_service.remove_compound(
                session,
                binding_id=compound.id,
                changeset_id=target_changeset.id,
                actor_id=target_changeset.owner_id,
                expected_version=target_changeset.version,
            ),
            lambda: RelationshipService().remove_relation(
                session,
                relation_id=relation.id,
                changeset_id=target_changeset.id,
                actor_id=target_changeset.owner_id,
                expected_version=target_changeset.version,
            ),
        ]

        for mutate in [*update_calls, *remove_calls]:
            with pytest.raises(BindingConflict, match="frozen base release"):
                mutate()


def test_binding_mutations_use_frozen_base_hashes_and_logical_keys(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Frozen binding base",
        )
        artifact = session.get(ReleaseArtifactManifest, fixture["release"].id)
        assert artifact is not None
        frozen_by_id = {
            str(row["id"]): row
            for rows in artifact.snapshot["bindings"].values()
            for row in rows
        }
        base = fixture["base_bindings"]
        base["region"].role = "mutated-live-region"
        base["asset"].role = "mutated-live-asset"
        base["compound"].label = "Mutated live label"
        base["compound"].logical_key = ""
        base["relation"].note = "Mutated live relation"
        session.flush()

        proposals = [
            BindingService().update_region(
                session,
                binding_id=base["region"].id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                role="reviewed",
                note="reviewed",
            ),
            BindingService().update_asset(
                session,
                binding_id=base["asset"].id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                role="reviewed",
                is_primary=False,
            ),
            BindingService().update_compound(
                session,
                binding_id=base["compound"].id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                label="Frozen label",
                role="reviewed",
                confidence=0.8,
                note="reviewed",
                is_primary=False,
                label_bbox=None,
            ),
            RelationshipService().update_relation(
                session,
                relation_id=base["relation"].id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                note="reviewed",
            ),
        ]

        for proposal, source in zip(proposals, base.values(), strict=True):
            frozen = frozen_by_id[str(source.id)]
            assert proposal.base_hash == binding_base_hash(frozen)
            assert proposal.logical_key == frozen["logical_key"]


def test_frozen_compound_binding_label_change_is_rejected_immediately(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session, include_base_bindings=True)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Reject frozen compound identity change",
        )
        original_version = changeset.version

        with pytest.raises(BindingConflict, match="remove.*add"):
            BindingService().update_compound(
                session,
                binding_id=fixture["base_bindings"]["compound"].id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                label="Renamed frozen label",
                role="reviewed",
                confidence=0.8,
                note="Identity fields cannot change in place",
                is_primary=False,
                label_bbox=None,
            )

        assert changeset.version == original_version
        assert session.scalar(
            select(VisualObjectCompoundBinding).where(
                VisualObjectCompoundBinding.changeset_id == changeset.id
            )
        ) is None


def test_same_draft_additions_remain_adds_and_are_cancelled_on_delete(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Edit same-draft additions",
        )
        bindings = BindingService()
        region = bindings.bind_region(
            session,
            object_id=fixture["source_object"].id,
            region_id=fixture["region"].id,
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
        )
        asset = bindings.bind_asset(
            session,
            object_id=fixture["source_object"].id,
            asset_id=fixture["asset"].id,
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
        )
        compound = bindings.bind_compound(
            session,
            object_id=fixture["source_object"].id,
            compound_id=fixture["compound"].id,
            label="Draft label",
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
        )
        relation = RelationshipService().create_relation(
            session,
            source_object_id=fixture["source_object"].id,
            target_object_id=fixture["target_object"].id,
            relation_type=ObjectRelationType.SUBSTITUENT_OF,
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
        )

        updated = [
            bindings.update_region(
                session,
                binding_id=region.id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                role="reviewed",
                note="reviewed",
            ),
            bindings.update_asset(
                session,
                binding_id=asset.id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                role="reviewed",
                is_primary=True,
            ),
            bindings.update_compound(
                session,
                binding_id=compound.id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                label="Updated draft label",
                role="reviewed",
                confidence=0.7,
                note="reviewed",
                is_primary=True,
                label_bbox=None,
            ),
            RelationshipService().update_relation(
                session,
                relation_id=relation.id,
                changeset_id=changeset.id,
                actor_id=changeset.owner_id,
                expected_version=changeset.version,
                note="reviewed",
            ),
        ]
        assert all(binding.operation == "add" for binding in updated)
        assert compound.logical_key.endswith(":Updated draft label")

        bindings.remove_region(
            session,
            binding_id=region.id,
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
        )
        bindings.remove_asset(
            session,
            binding_id=asset.id,
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
        )
        bindings.remove_compound(
            session,
            binding_id=compound.id,
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
        )
        RelationshipService().remove_relation(
            session,
            relation_id=relation.id,
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
        )

        assert session.get(VisualObjectRegionBinding, region.id) is None
        assert session.get(VisualObjectAssetBinding, asset.id) is None
        assert session.get(VisualObjectCompoundBinding, compound.id) is None
        assert session.get(VisualObjectRelation, relation.id) is None


def test_scientific_approval_evidence_uses_frozen_submission_and_base_release(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, _, release = _setup(
            session,
            finalize_release=False,
        )
        fixture = _add_visual_release_content(
            session,
            release=release,
            admin_id=admin.id,
            paper_id=paper.id,
        )
        review = ReviewService()
        task = review.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = review.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Frozen scientific approval evidence",
            reason="Prove approval evidence cannot drift",
        )
        structure_item = session.scalar(
            select(ReleaseItem).where(
                ReleaseItem.release_id == release.id,
                ReleaseItem.object_id == fixture["structure_id"],
            )
        )
        assert structure_item is not None
        structure_revision = session.get(ObjectRevision, structure_item.revision_id)
        assert structure_revision is not None
        item = review.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
            object_id=fixture["structure_id"],
            object_kind=ObjectKind.STRUCTURE.value,
            base_revision_id=structure_revision.id,
            proposed_snapshot=dict(structure_revision.snapshot),
        )
        submitted_structure = {
            **structure_revision.snapshot,
            "review_status": "reviewed",
        }
        review.update_changeset_item(
            session,
            changeset_id=changeset.id,
            item_id=item.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
            proposed_snapshot=submitted_structure,
        )
        BindingService().update_region(
            session,
            binding_id=fixture["region_binding_id"],
            changeset_id=changeset.id,
            actor_id=changeset.owner_id,
            expected_version=changeset.version,
            role="reviewed-source",
            note="Reviewed against the source PDF",
        )
        review.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
        )
        submission_version = changeset.version
        submission_hash = changeset.submitted_content_hash
        ApprovalService().request_changes(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            expected_version=changeset.version,
            reason="Verify evidence remains bound to the submitted version",
        )
        assert changeset.version == submission_version + 1

        region_item = session.scalar(
            select(ReleaseItem).where(
                ReleaseItem.release_id == release.id,
                ReleaseItem.object_id == fixture["region_id"],
            )
        )
        assert region_item is not None
        region_revision = session.get(ObjectRevision, region_item.revision_id)
        structure = session.get(Structure, fixture["structure_id"])
        region = session.get(VisualRegion, fixture["region_id"])
        assert region_revision is not None
        assert structure is not None
        assert region is not None
        RevisionService().create_revision(
            session,
            object_identity=structure,
            actor_id=admin.id,
            reason="Unrelated later structure draft",
            snapshot={"canonical_smiles": "NNN", "drawing_asset_id": None},
            predecessor=structure_revision,
        )
        RevisionService().create_revision(
            session,
            object_identity=region,
            actor_id=admin.id,
            reason="Unrelated later Region draft",
            snapshot={"region_key": region.region_key, "page_number": 99},
            predecessor=region_revision,
        )

        evidence = ApprovalService().scientific_evidence(session, changeset.id)

        assert evidence == {
            "changeset_id": str(changeset.id),
            "base_release_id": str(release.id),
            "submission_version": submission_version,
            "snapshot_hash": submission_hash,
            "structures": [
                {
                    "object_id": str(structure.id),
                    "before": structure_revision.snapshot,
                    "after": submitted_structure,
                }
            ],
            "regions": [
                {
                    "object_id": str(region.id),
                    "before": region_revision.snapshot,
                    "after": region_revision.snapshot,
                }
            ],
        }


def test_approved_visual_binding_deltas_are_snapshotted_and_published(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        changeset = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Approved binding draft",
        )
        _add_all_binding_deltas(session, fixture, changeset)
        _submit_and_approve(session, fixture, fixture["reviewer"], changeset)

        binding_delta = changeset.submitted_snapshot["binding_delta"]
        assert all(len(rows) == 1 for rows in binding_delta.values())
        assert all(
            row["changeset_id"] == str(changeset.id)
            for rows in binding_delta.values()
            for row in rows
        )

        published = publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=fixture["admin"].id,
            idempotency_key="publish-approved-bindings",
        ).release
        artifact = session.get(ReleaseArtifactManifest, published.id)

        assert artifact is not None
        assert artifact.snapshot["bindings"] == binding_delta


def test_rollback_base_prevents_old_binding_delta_from_reappearing(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        fixture = _binding_release_fixture(session)
        first = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Publish then roll back binding",
        )
        _add_all_binding_deltas(session, fixture, first)
        _submit_and_approve(session, fixture, fixture["reviewer"], first)
        publish_approved_changeset(
            session,
            changeset_id=first.id,
            actor_id=fixture["admin"].id,
            idempotency_key="publish-bindings-before-rollback",
        )
        rollback = rollback_release(
            session,
            target_release_id=fixture["release"].id,
            actor_id=fixture["admin"].id,
            reason="Remove the approved visual binding delta",
            idempotency_key="rollback-bindings",
        ).release

        paper_item = session.scalar(
            select(ReleaseItem).where(
                ReleaseItem.release_id == rollback.id,
                ReleaseItem.object_id == fixture["paper"].id,
            )
        )
        assert paper_item is not None
        fixture["release"] = rollback
        fixture["paper_revision"] = session.get(ObjectRevision, paper_item.revision_id)
        second = _paper_changeset(
            session,
            fixture,
            fixture["reviewer"],
            title="Independent change after rollback",
        )
        _submit_and_approve(session, fixture, fixture["reviewer"], second)
        published = publish_approved_changeset(
            session,
            changeset_id=second.id,
            actor_id=fixture["admin"].id,
            idempotency_key="publish-after-binding-rollback",
        ).release
        artifact = session.get(ReleaseArtifactManifest, published.id)

        assert artifact is not None
        assert all(not rows for rows in artifact.snapshot["bindings"].values())


def test_candidate_rejects_tombstoned_compound_with_retained_references(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, _, release = _setup(
            session, finalize_release=False
        )
        compound = Compound(
            paper_id=paper.id,
            local_identity="closure-compound",
            display_label="Closure compound",
            normalized_label="closure compound",
        )
        evidence = Evidence(paper_id=paper.id, evidence_key="closure-evidence")
        lineage = Lineage(paper_id=paper.id, lineage_key="closure-lineage")
        visual_object = VisualObject(
            paper_id=paper.id,
            object_key="closure-visual",
            object_type="complete_molecule",
        )
        session.add_all([compound, evidence, lineage, visual_object])
        session.flush()
        structure = Structure(
            paper_id=paper.id,
            compound_id=compound.id,
            structure_key="closure-structure",
        )
        activity = Activity(
            paper_id=paper.id,
            compound_id=compound.id,
            activity_key="closure-activity",
        )
        edge = LineageEdge(
            paper_id=paper.id,
            lineage_id=lineage.id,
            edge_key="closure-edge",
            parent_compound_id=None,
            derived_compound_id=compound.id,
        )
        session.add_all([structure, activity, edge])
        session.flush()
        compound_revision = _append_published_item(
            session,
            release=release,
            identity=compound,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={
                "local_identity": compound.local_identity,
                "display_label": compound.display_label,
            },
            order=2,
        )
        _append_published_item(
            session,
            release=release,
            identity=structure,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={
                "structure_key": structure.structure_key,
                "compound_id": str(compound.id),
                "drawing_asset_id": None,
            },
            order=3,
        )
        _append_published_item(
            session,
            release=release,
            identity=evidence,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={
                "evidence_key": evidence.evidence_key,
                "compound_ids": [str(compound.id)],
            },
            order=4,
        )
        _append_published_item(
            session,
            release=release,
            identity=activity,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={
                "activity_key": activity.activity_key,
                "compound_id": str(compound.id),
                "evidence_ids": [str(evidence.id)],
            },
            order=5,
        )
        _append_published_item(
            session,
            release=release,
            identity=lineage,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={"lineage_key": lineage.lineage_key},
            order=6,
        )
        _append_published_item(
            session,
            release=release,
            identity=edge,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={
                "edge_key": edge.edge_key,
                "lineage_id": str(lineage.id),
                "parent_compound_id": None,
                "derived_compound_id": str(compound.id),
                "evidence_ids": [str(evidence.id)],
                "relation_status": "human_confirmed",
            },
            order=7,
        )
        _append_published_item(
            session,
            release=release,
            identity=visual_object,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={
                "object_key": visual_object.object_key,
                "object_type": "complete_molecule",
            },
            order=8,
        )
        session.add(
            VisualObjectCompoundBinding(
                visual_object_id=visual_object.id,
                compound_id=compound.id,
                label="1",
                logical_key=(
                    f"compound:{visual_object.id}:{compound.id}:1"
                ),
                role="label",
                is_primary=True,
            )
        )
        release.manifest_finalized = True
        session.flush()
        capture_release_artifact_manifest(session, release.id)

        review = ReviewService()
        task = review.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = review.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Remove a referenced compound",
            reason="Exercise release reference closure",
        )
        item = review.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
            object_id=compound.id,
            object_kind=ObjectKind.COMPOUND.value,
            base_revision_id=compound_revision.id,
            proposed_snapshot={
                "local_identity": compound.local_identity,
                "display_label": compound.display_label,
                "deleted": True,
            },
        )
        tombstone = RevisionService().create_revision(
            session,
            object_identity=compound,
            actor_id=reviewer.id,
            reason="Remove compound",
            snapshot=dict(item.proposed_snapshot),
            predecessor=compound_revision,
            changeset_id=changeset.id,
            workflow_state=WorkflowState.DRAFT,
            is_tombstone=True,
        )
        item.proposed_revision_id = tombstone.id
        session.flush()

        result = validate_release(
            session, release.id, changeset_id=changeset.id
        )

        dangling_ids = {
            issue.object_id
            for issue in result.issues
            if issue.code in {"dangling_reference", "invalid_endpoint"}
        }
        assert result.valid is False
        assert {structure.id, evidence.id, activity.id, edge.id, visual_object.id} <= dangling_ids


def test_release_validation_checks_drawing_assets_in_revision_snapshots(
    auth_session_factory,
    tmp_path,
) -> None:
    with auth_session_factory.begin() as session:
        _, _, admin, paper, _, release = _setup(session, finalize_release=False)
        compound = Compound(
            paper_id=paper.id,
            local_identity="asset-compound",
            display_label="Asset compound",
            normalized_label="asset compound",
        )
        session.add(compound)
        session.flush()
        structure = Structure(
            paper_id=paper.id,
            compound_id=compound.id,
            structure_key="asset-structure",
        )
        drawing = Asset(
            storage_key="managed/structures/missing.png",
            original_filename="missing.png",
            sha256="a" * 64,
            byte_size=128,
            mime_type="image/png",
            category=AssetCategory.RDKIT_STRUCTURE,
            access_level=AssetAccessLevel.VISITOR,
            integrity_state=AssetIntegrityState.VERIFIED,
        )
        session.add_all([structure, drawing])
        session.flush()
        _append_published_item(
            session,
            release=release,
            identity=compound,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={"local_identity": compound.local_identity},
            order=2,
        )
        _append_published_item(
            session,
            release=release,
            identity=structure,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={
                "structure_key": structure.structure_key,
                "compound_id": str(compound.id),
                "drawing_asset_id": str(drawing.id),
            },
            order=3,
        )
        release.manifest_finalized = True
        session.flush()

        from app.assets.storage import LocalAssetStore

        result = validate_release(
            session,
            release.id,
            asset_store=LocalAssetStore(tmp_path),
        )

        assert result.valid is False
        assert any(
            issue.code == "missing_asset" and issue.object_id == structure.id
            for issue in result.issues
        )


def test_historical_export_is_unchanged_after_mutable_binding_edit(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, _, admin, paper, _, release = _setup(session, finalize_release=False)
        compound = Compound(
            paper_id=paper.id,
            local_identity="export-compound",
            display_label="Export compound",
            normalized_label="export compound",
        )
        visual_object = VisualObject(
            paper_id=paper.id,
            object_key="export-visual",
            object_type="complete_molecule",
        )
        session.add_all([compound, visual_object])
        session.flush()
        _append_published_item(
            session,
            release=release,
            identity=compound,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={"local_identity": compound.local_identity},
            order=2,
        )
        _append_published_item(
            session,
            release=release,
            identity=visual_object,
            actor_id=admin.id,
            paper_id=paper.id,
            snapshot={
                "object_key": visual_object.object_key,
                "object_type": "complete_molecule",
            },
            order=3,
        )
        binding = VisualObjectCompoundBinding(
            visual_object_id=visual_object.id,
            compound_id=compound.id,
            label="7a",
            role="label",
            is_primary=True,
        )
        session.add(binding)
        release.manifest_finalized = True
        session.flush()
        capture_release_artifact_manifest(session, release.id)

        first = export_release(session, release.id)
        binding.label = "draft-label-that-must-not-change-history"
        session.flush([binding])
        second = export_release(session, release.id)

        assert second == first
        assert verify_release_export(second)


def test_approval_is_immutable_and_duplicate_request_is_idempotent(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, _, changeset, approved = _approved_changeset(session)
        duplicate = ApprovalService().approve(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            expected_version=4,
            reason="Retry after a lost response",
        )

        assert duplicate.idempotent is True
        assert duplicate.decision.id == approved.decision.id
        assert approved.decision.snapshot == changeset.submitted_snapshot
        assert approved.decision.snapshot_hash == changeset.submitted_content_hash


@pytest.mark.parametrize(
    "fail_stage",
    [
        "before_asset_preparation",
        "after_asset_preparation",
        "final_transaction",
        "before_pointer_switch",
    ],
)
def test_release_failure_keeps_current_release(
    auth_session_factory,
    fail_stage: str,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, release, changeset, _ = _approved_changeset(session)
        release_id = release.id
        changeset_id = changeset.id
        admin_id = admin.id

    with pytest.raises(RuntimeError, match="Injected failure"):
        with auth_session_factory.begin() as session:
            publish_approved_changeset(
                session,
                changeset_id=changeset_id,
                actor_id=admin_id,
                fail_stage=fail_stage,
            )

    with auth_session_factory.begin() as session:
        current = session.scalar(select(Release).where(Release.is_current.is_(True)))
        assert current is not None
        assert current.id == release_id


def test_concurrent_publication_is_serialized_and_idempotent(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, _, changeset, _ = _approved_changeset(session)
        changeset_id = changeset.id
        admin_id = admin.id

    barrier = Barrier(2)
    guard = Lock()
    results: list[bool] = []
    failures: list[BaseException] = []

    def publish() -> None:
        try:
            with auth_session_factory.begin() as session:
                barrier.wait(timeout=5)
                result = publish_approved_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=admin_id,
                    idempotency_key="concurrent-publication",
                )
            with guard:
                results.append(result.idempotent)
        except BaseException as error:
            with guard:
                failures.append(error)

    threads = [Thread(target=publish, name=f"release-publisher-{index}") for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert sorted(results) == [False, True]
    with auth_session_factory.begin() as session:
        current_releases = list(
            session.scalars(select(Release).where(Release.is_current.is_(True)))
        )
        assert len(current_releases) == 1


def test_publish_physically_validates_once_before_metadata_rechecks(
    auth_session_factory,
    monkeypatch,
) -> None:
    original_validate = release_service.validate_release
    validated_stores: list[object | None] = []
    store = object()

    def track_validate(*args, asset_store=None, **kwargs):
        validated_stores.append(asset_store)
        return original_validate(*args, asset_store=asset_store, **kwargs)

    monkeypatch.setattr(release_service, "validate_release", track_validate)

    with auth_session_factory.begin() as session:
        _, admin, _, _, changeset, _ = _approved_changeset(session)
        publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            asset_store=store,
            idempotency_key="physical-validation-retry",
        )
        assert validated_stores[0] is store
        assert all(value is None for value in validated_stores[1:])

        validated_stores.clear()
        duplicate = publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            asset_store=store,
            idempotency_key="physical-validation-retry",
        )
        assert duplicate.idempotent is True
        assert validated_stores[0] is store
        assert all(value is None for value in validated_stores[1:])


def test_rollback_physically_validates_once_before_metadata_rechecks(
    auth_session_factory,
    monkeypatch,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, release, changeset, _ = _approved_changeset(session)
        publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
        )
        target_release_id = release.id
        admin_id = admin.id

    original_validate = release_service.validate_release
    validated_stores: list[object | None] = []
    store = object()

    def track_validate(*args, asset_store=None, **kwargs):
        validated_stores.append(asset_store)
        return original_validate(*args, asset_store=asset_store, **kwargs)

    monkeypatch.setattr(release_service, "validate_release", track_validate)

    with auth_session_factory.begin() as session:
        rollback_release(
            session,
            target_release_id=target_release_id,
            actor_id=admin_id,
            reason="Restore physically verified assets",
            asset_store=store,
        )

    assert validated_stores[0] is store
    assert all(value is None for value in validated_stores[1:])


def test_publish_export_and_rollback_create_immutable_new_releases(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, release, changeset, _ = _approved_changeset(session)
        original_release_id = release.id
        result = publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            notes="Task 21 publish",
        )
        published_id = result.release.id
        admin_id = admin.id
        assert result.release.is_current is True
        first_export = export_release(session, published_id)
        second_export = export_release(session, published_id)
        assert first_export == second_export
        assert first_export["sha256_manifest"]["payload"]
        assert verify_release_export(first_export)

    with auth_session_factory.begin() as session:
        rollback = rollback_release(
            session,
            target_release_id=original_release_id,
            actor_id=admin_id,
            reason="Restore the previous reviewed dataset",
        )
        assert rollback.release.is_current is True
        assert rollback.release.id not in {original_release_id, published_id}
        assert rollback.replaced_release_id == published_id
        target_snapshots = [
            session.get(ObjectRevision, item.revision_id).snapshot
            for item in session.scalars(
                select(ReleaseItem).where(ReleaseItem.release_id == original_release_id)
            )
        ]
        rollback_snapshots = [
            session.get(ObjectRevision, item.revision_id).snapshot
            for item in session.scalars(
                select(ReleaseItem).where(ReleaseItem.release_id == rollback.release.id)
            )
        ]
        assert rollback_snapshots == target_snapshots


def test_rollback_publishes_tombstones_for_objects_absent_from_target(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, baseline = _setup(session)
        capture_release_artifact_manifest(session, baseline.id)
        review = ReviewService()
        task = review.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = review.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=baseline.id,
            title="Publish a new compound",
            reason="Verify rollback removal semantics",
        )
        _add_paper_item(
            session,
            review,
            changeset,
            reviewer,
            paper,
            paper_revision,
        )
        compound = Compound(
            paper_id=paper.id,
            local_identity="rollback-new-compound",
            display_label="Rollback new compound",
            normalized_label="rollback new compound",
        )
        session.add(compound)
        session.flush()
        review.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
            object_id=compound.id,
            object_kind=ObjectKind.COMPOUND.value,
            base_revision_id=None,
            proposed_snapshot={
                "local_identity": compound.local_identity,
                "display_label": compound.display_label,
            },
        )
        review.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
        )
        ApprovalService().approve(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            expected_version=changeset.version,
            reason="Approve the new compound",
        )
        publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
        )
        compound_id = compound.id
        baseline_id = baseline.id
        admin_id = admin.id

    with auth_session_factory.begin() as session:
        result = rollback_release(
            session,
            target_release_id=baseline_id,
            actor_id=admin_id,
            reason="Remove objects introduced after the baseline",
        )
        tombstone = session.scalar(
            select(ObjectRevision).where(
                ObjectRevision.object_id == compound_id,
                ObjectRevision.is_current_published.is_(True),
            )
        )
        released_compound = session.scalar(
            select(ReleaseItem).where(
                ReleaseItem.release_id == result.release.id,
                ReleaseItem.object_id == compound_id,
            )
        )

        assert tombstone is not None
        assert tombstone.is_tombstone is True
        assert released_compound is None


def test_rollback_is_persistently_idempotent_and_auditable(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, baseline, changeset, _ = _approved_changeset(session)
        published = publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
        ).release
        baseline_id = baseline.id
        published_id = published.id
        admin_id = admin.id

    with auth_session_factory.begin() as session:
        first = rollback_release(
            session,
            target_release_id=baseline_id,
            actor_id=admin_id,
            reason="Restore the audited baseline",
            idempotency_key="rollback-audited-baseline",
        )
        first_release_id = first.release.id
        operation = session.scalar(
            select(ReleaseOperation).where(
                ReleaseOperation.result_release_id == first.release.id
            )
        )
        assert first.idempotent is False
        assert operation is not None
        assert operation.target_release_id == baseline_id
        assert operation.replaced_release_id == published_id
        assert operation.delta["objects"]
        assert all(
            {"paper_id", "object_id", "action", "before_hash", "after_hash"}
            <= set(item)
            for item in operation.delta["objects"]
        )

    with auth_session_factory.begin() as session:
        duplicate = rollback_release(
            session,
            target_release_id=baseline_id,
            actor_id=admin_id,
            reason="Restore the audited baseline",
            idempotency_key="rollback-audited-baseline",
        )
        assert duplicate.idempotent is True
        assert duplicate.release.id == first_release_id
        assert session.scalar(select(ReleaseOperation).where(
            ReleaseOperation.idempotency_key == "rollback-audited-baseline"
        )) is not None


def test_publish_uses_persistent_idempotency_key(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, _, changeset, _ = _approved_changeset(session)
        first = publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            title="Idempotent publication",
            notes="Persist the publication request",
            idempotency_key="publish-approved-changeset",
        )
        first_release_id = first.release.id
        operation = session.scalar(
            select(ReleaseOperation).where(
                ReleaseOperation.result_release_id == first.release.id
            )
        )
        assert operation is not None
        assert operation.operation_type == "publish"

    with auth_session_factory.begin() as session:
        duplicate = publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            title="Idempotent publication",
            notes="Persist the publication request",
            idempotency_key="publish-approved-changeset",
        )
        assert duplicate.idempotent is True
        assert duplicate.release.id == first_release_id
        assert duplicate.operation_id == operation.id


def test_publish_rejects_changed_request_for_a_persisted_idempotency_key(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, _, changeset, _ = _approved_changeset(session)
        changeset_id = changeset.id
        admin_id = admin.id
        publish_approved_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=admin_id,
            title="Original publication title",
            idempotency_key="publish-request-hash",
        )

    with auth_session_factory.begin() as session:
        with pytest.raises(ReleaseConflict, match="another publication"):
            publish_approved_changeset(
                session,
                changeset_id=changeset_id,
                actor_id=admin_id,
                title="Changed publication title",
                idempotency_key="publish-request-hash",
            )


def test_publish_rejects_new_idempotency_key_for_published_changeset(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, _, changeset, _ = _approved_changeset(session)
        publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            title="One publication",
            idempotency_key="original-publish-key",
        )

        with pytest.raises(ReleaseConflict, match="already published"):
            publish_approved_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=admin.id,
                title="One publication",
                idempotency_key="new-publish-key",
            )


def test_release_preview_reports_categorized_delta_and_validation(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, admin, _, _, changeset, _ = _approved_changeset(session)
        preview = preview_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
        )

        assert preview["changeset_id"] == str(changeset.id)
        assert preview["counts"] == {
            "create": 0,
            "update": 1,
            "tombstone": 0,
            "total": 1,
        }
        assert preview["by_object_kind"]["paper"]["update"] == 1
        assert preview["validation"]["valid"] is True
        assert preview["affected_asset_ids"] == []


def test_release_export_restores_into_empty_disposable_database(
    auth_session_factory,
    postgresql_database_url,
) -> None:
    from sqlalchemy import text

    with auth_session_factory.begin() as session:
        _, _, admin, paper, _, published = _setup(
            session,
            finalize_release=False,
        )
        expected = _add_visual_release_content(
            session,
            release=published,
            admin_id=admin.id,
            paper_id=paper.id,
        )
        source_payload = export_release(session, published.id)
        assert {row["id"] for row in source_payload["compounds"]} == {
            str(expected["compound_id"])
        }
        assert {row["id"] for row in source_payload["structures"]} == {
            str(expected["structure_id"])
        }
        assert {row["id"] for row in source_payload["regions"]} == {
            str(expected["region_id"])
        }
        assert {row["id"] for row in source_payload["visual_objects"]} == {
            str(expected["visual_object_id"])
        }
        assert {row["id"] for row in source_payload["asset_manifest"]} == {
            str(expected["asset_id"])
        }
        assert source_payload["bindings"]["visual_object_regions"]
        assert source_payload["bindings"]["visual_object_compounds"]
        vocabularies = source_payload["vocabularies"]
        assert {
            "object_kinds",
            "workflow_states",
            "structure_states",
            "evidence_states",
            "activity_states",
            "asset_categories",
            "asset_access_levels",
            "asset_integrity_states",
            "molecule_object_types",
        } <= set(vocabularies)
        assert "source_structure_mismatch" in vocabularies["structure_states"]
        assert "complete_molecule" in vocabularies["molecule_object_types"]

    schema = f"release_restore_{uuid4().hex}"
    source_engine = auth_session_factory.kw["bind"]
    with source_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    disposable_url = make_url(postgresql_database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        disposable_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    config.attributes["leadtrace_database_url"] = disposable_url.render_as_string(
        hide_password=False
    )
    config.attributes["leadtrace_expected_database_name"] = make_url(
        postgresql_database_url
    ).database
    command.upgrade(config, "head")
    disposable_engine = create_database_engine(
        disposable_url.render_as_string(hide_password=False)
    )
    try:
        disposable_factory = create_session_factory(disposable_engine)
        with disposable_factory.begin() as session:
            class MetadataStore:
                def inspect(self, storage_key):
                    row = next(
                        item
                        for item in source_payload["asset_manifest"]
                        if item["storage_key"] == storage_key
                    )
                    return SimpleNamespace(
                        path=Path("/virtual/" + storage_key),
                        sha256=row["sha256"],
                        byte_size=row["byte_size"],
                        mime_type=row["mime_type"],
                    )

            restored = restore_release_export(
                session,
                source_payload,
                asset_store=MetadataStore(),
            )
            restored_payload = export_release(session, restored.id)
            assert restored_payload == source_payload
            assert verify_release_export(restored_payload)
    finally:
        disposable_engine.dispose()
        with source_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_approval_migration_backfills_existing_release_artifact_manifest(
    empty_postgresql_database_url,
) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", empty_postgresql_database_url)
    config.attributes["leadtrace_database_url"] = empty_postgresql_database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        empty_postgresql_database_url
    ).database
    command.upgrade(config, "0012_molecule_objects")

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory.begin() as session:
            _, _, admin, paper, _, release = _setup(
                session,
                finalize_release=False,
            )
            fixture = _add_visual_release_content(
                session,
                release=release,
                admin_id=admin.id,
                paper_id=paper.id,
                legacy_binding_schema=True,
            )
            outside_compound = Compound(
                paper_id=paper.id,
                local_identity="outside-old-release",
                display_label="Outside old release",
                normalized_label="outside old release",
            )
            outside_region = VisualRegion(
                paper_id=paper.id,
                region_key="outside-old-release",
                page_number=9,
            )
            outside_object = VisualObject(
                paper_id=paper.id,
                object_key="outside-old-release",
                object_type="r_group",
            )
            session.add_all([outside_compound, outside_region, outside_object])
            session.flush()
            session.execute(
                text(
                    """
                    INSERT INTO visual_object_compound_bindings (
                        id, visual_object_id, compound_id, label, role,
                        confidence, note, is_primary
                    ) VALUES (
                        :id, :source_id, :target_id, 'future', 'label',
                        NULL, NULL, false
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "source_id": fixture["visual_object_id"],
                    "target_id": outside_compound.id,
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO visual_object_region_bindings (
                        id, visual_object_id, region_id, role, note
                    ) VALUES (:id, :source_id, :target_id, 'source', NULL)
                    """
                ),
                {
                    "id": uuid4(),
                    "source_id": fixture["visual_object_id"],
                    "target_id": outside_region.id,
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO visual_object_relations (
                        id, source_object_id, target_object_id, relation_type, note
                    ) VALUES (:id, :source_id, :target_id, 'contains', NULL)
                    """
                ),
                {
                    "id": uuid4(),
                    "source_id": fixture["visual_object_id"],
                    "target_id": outside_object.id,
                },
            )
            release_id = release.id
            binding_id = fixture["compound_binding_id"]
            outside_ids = {
                str(outside_compound.id),
                str(outside_region.id),
                str(outside_object.id),
            }
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory.begin() as session:
            manifest = session.get(ReleaseArtifactManifest, release_id)
            assert manifest is not None
            assert manifest.snapshot["capture_mode"] == "migration_best_effort"
            assert manifest.content_hash == canonical_hash(manifest.snapshot)
            serialized_bindings = str(manifest.snapshot["bindings"])
            assert all(outside_id not in serialized_bindings for outside_id in outside_ids)
            assert len(manifest.snapshot["bindings"]["visual_object_regions"]) == 1
            assert len(manifest.snapshot["bindings"]["visual_object_compounds"]) == 1
            assert manifest.snapshot["bindings"]["visual_object_relations"] == []
            assert validate_release(session, release_id).valid is True

            binding = session.get(VisualObjectCompoundBinding, binding_id)
            assert binding is not None
            binding.label = "unpublished-draft-label"
            session.flush([binding])

            exported = export_release(session, release_id)
            exported_bindings = exported["bindings"]["visual_object_compounds"]
            assert exported_bindings[0]["label"] == "7a"
    finally:
        engine.dispose()


def test_approval_migration_downgrade_discards_parallel_draft_binding_deltas(
    empty_postgresql_database_url,
) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", empty_postgresql_database_url)
    config.attributes["leadtrace_database_url"] = empty_postgresql_database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        empty_postgresql_database_url
    ).database
    command.upgrade(config, "head")

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with create_session_factory(engine).begin() as session:
            fixture = _binding_release_fixture(session)
            first = _paper_changeset(
                session,
                fixture,
                fixture["reviewer"],
                title="First parallel binding delta",
            )
            second = _paper_changeset(
                session,
                fixture,
                fixture["other"],
                title="Second parallel binding delta",
            )
            first_binding = BindingService().bind_region(
                session,
                object_id=fixture["source_object"].id,
                region_id=fixture["region"].id,
                changeset_id=first.id,
                actor_id=first.owner_id,
                expected_version=first.version,
            )
            second_binding = BindingService().bind_region(
                session,
                object_id=fixture["source_object"].id,
                region_id=fixture["region"].id,
                changeset_id=second.id,
                actor_id=second.owner_id,
                expected_version=second.version,
            )
            binding_ids = (first_binding.id, second_binding.id)
    finally:
        engine.dispose()

    command.downgrade(config, "0012_molecule_objects")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.connect() as connection:
            remaining = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM visual_object_region_bindings
                    WHERE id IN (:first_id, :second_id)
                    """
                ),
                {"first_id": binding_ids[0], "second_id": binding_ids[1]},
            )
            assert remaining == 0
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.connect() as connection:
            columns = set(
                connection.scalars(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'visual_object_region_bindings'
                        """
                    )
                )
            )
            assert {
                "changeset_id",
                "operation",
                "logical_key",
                "base_hash",
            } <= columns
    finally:
        engine.dispose()


def test_rollback_supersedes_only_changesets_whose_content_is_replaced(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, admin, paper, baseline, first_changeset, _ = _approved_changeset(
            session
        )
        first_release = publish_approved_changeset(
            session,
            changeset_id=first_changeset.id,
            actor_id=admin.id,
        ).release
        review = ReviewService()
        task = review.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        second = review.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=first_release.id,
            title="Add an object after the target release",
            reason="Exercise selective rollback supersession",
        )
        compound = Compound(
            paper_id=paper.id,
            local_identity="selective-rollback-compound",
            display_label="Selective rollback compound",
            normalized_label="selective rollback compound",
        )
        session.add(compound)
        session.flush()
        item = review.add_changeset_item(
            session,
            changeset_id=second.id,
            actor_id=reviewer.id,
            expected_version=second.version,
            object_id=compound.id,
            object_kind=ObjectKind.COMPOUND.value,
            proposed_snapshot={
                "local_identity": compound.local_identity,
                "display_label": compound.display_label,
            },
        )
        revision = RevisionService().create_revision(
            session,
            object_identity=compound,
            actor_id=reviewer.id,
            reason="Add compound",
            snapshot=dict(item.proposed_snapshot),
            changeset_id=second.id,
            workflow_state=WorkflowState.DRAFT,
        )
        item.proposed_revision_id = revision.id
        review.submit_changeset(
            session,
            changeset_id=second.id,
            actor_id=reviewer.id,
            expected_version=second.version,
        )
        ApprovalService().approve(
            session,
            changeset_id=second.id,
            actor_id=admin.id,
            expected_version=second.version,
            reason="Approve second release",
        )
        publish_approved_changeset(
            session,
            changeset_id=second.id,
            actor_id=admin.id,
        )
        target_id = first_release.id
        first_id = first_changeset.id
        second_id = second.id
        admin_id = admin.id

    with auth_session_factory.begin() as session:
        rollback_release(
            session,
            target_release_id=target_id,
            actor_id=admin_id,
            reason="Remove only the later compound",
            idempotency_key="selective-supersession",
        )
        first = session.get(Changeset, first_id)
        second = session.get(Changeset, second_id)
        assert first.workflow_state is WorkflowState.PUBLISHED
        assert second.workflow_state is WorkflowState.SUPERSEDED


def test_physical_asset_preparation_occurs_before_publication_lock(
    auth_session_factory,
    monkeypatch,
) -> None:
    events: list[str] = []
    original_validate = release_service.validate_release

    def track_validate(*args, asset_store=None, **kwargs):
        events.append("physical_validation" if asset_store is not None else "metadata_validation")
        return original_validate(*args, asset_store=asset_store, **kwargs)

    def track_lock(_session) -> None:
        events.append("publication_lock")

    monkeypatch.setattr(release_service, "validate_release", track_validate)
    monkeypatch.setattr(release_service, "_advisory_lock", track_lock)

    with auth_session_factory.begin() as session:
        _, admin, _, _, changeset, _ = _approved_changeset(session)
        publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            asset_store=object(),
        )

    assert events[0] == "physical_validation"
    assert events.index("physical_validation") < events.index("publication_lock")
    assert "physical_validation" not in events[events.index("publication_lock") + 1 :]
