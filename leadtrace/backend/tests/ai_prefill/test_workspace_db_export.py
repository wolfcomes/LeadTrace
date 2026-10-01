from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.ai_prefill import workspace_export
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.preview_application import PreviewApplicationService
from app.activities.models import Activity, ActivityOperator
from app.activities.service import ActivityService
from app.compounds.models import Compound
from app.compounds.service import CompoundService
from app.evidence.models import Evidence
from app.security.policies import Principal
from app.structures.models import StructureInputMethod, StructureStatus
from app.structures.service import StructureService
from app.users.models import UserRole
from app.workspaces.models import PaperWorkspace
from app.workspaces.snapshot import canonical_snapshot_hash

from .test_contract import complete_payload
from .test_preview_application import make_candidate


def _apply(context, settings, payload=None):
    parent = make_candidate(AiPrefillPayload.model_validate(payload or complete_payload()))
    with context.session_factory.begin() as session:
        result = PreviewApplicationService(settings=settings).apply(
            session, instance_id=settings.preview_instance_id,
            idempotency_key="workspace-export-parent", candidate=parent,
            validation_report=validate_candidate(parent), actor_id=context.admin_id,
            paper_id=context.paper_id, workspace_id=context.workspace_id,
            expected_workspace_version=1,
        )
        return parent, result.receipt.application_id


def _export(session, parent, application_id, settings, version=2):
    function = getattr(workspace_export, "export_workspace_candidate", None)
    assert callable(function), "actual database Workspace -> Candidate export is missing"
    return function(
        session, parent, application_id=application_id, settings=settings,
        expected_workspace_version=version, candidate_id="candidate:human-child",
        evaluation_id="evaluation:human-review", reviewer="reviewer:test",
    )


def test_exports_edited_database_rows_with_existing_and_new_refs(preview_ai_context, preview_settings):
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    original_hash = parent.hashes
    actor = Principal(context.reviewer_id, UserRole.REVIEWER)
    with context.session_factory.begin() as session:
        lead = session.scalar(select(Compound).where(Compound.compound_label == "Lead 1"))
        CompoundService().update_compound(session, compound_id=lead.id, expected_version=2,
            actor=actor, updates={"description": "Human corrected starting lead"})
        result = CompoundService().create_compound(session, workspace_id=context.workspace_id,
            expected_version=3, actor=actor, compound_label="Human 21", display_name=None,
            description="Added after reading the PDF")
        compound_id = result.compound.id
        StructureService(preview_settings.asset_root).upsert_structure(
            session, compound_id=compound_id, expected_version=4, actor=actor,
            status=StructureStatus.REVIEWER_CONFIRMED,
            input_method=StructureInputMethod.MANUAL_SMILES, smiles="CCC", molfile=None,
        )
        ActivityService().create_activity(session, compound_id=compound_id,
            expected_version=5, actor=actor, evidence_id=None, assay_name="Human assay",
            metric="IC50", operator=ActivityOperator.LESS_THAN, value=Decimal("0.0125"),
            unit="uM", context_value="Human correction")
    with context.session_factory.begin() as session:
        exported = _export(session, parent, application_id, preview_settings, version=6)
    child = exported.candidate
    assert child.producer.kind == "human-assisted"
    assert child.producer.engine_version == "workspace-export-v1"
    assert child.parent_candidate_id == parent.candidate_id
    assert child.input_evaluation_ids == ["evaluation:human-review"]
    assert parent.hashes == original_hash
    assert child.payload.compounds[0].ref == "compound:lead-1"
    assert child.payload.compounds[0].description == "Human corrected starting lead"
    added = next(row for row in child.payload.compounds if row.compound_label == "Human 21")
    assert added.ref.startswith("human:compound:")
    assert added.structure.smiles == "CCC"
    activity = next(row for row in child.payload.activities if row.assay_name == "Human assay")
    assert activity.compound_ref == added.ref
    assert activity.value == Decimal("0.0125") and activity.operator == "<"
    assert child.payload.lineages[0].edges[0].ref == "edge:lead-1-to-18"
    assert child.payload.evidence[0].ref == "evidence:scheme-2"
    assert child.payload.structure_locators[0].ref == "structure-image:lead-1"
    assert exported.workspace_version == 6
    assert exported.snapshot_sha256 == canonical_snapshot_hash(exported.snapshot)
    assert validate_candidate(child).can_apply
    assert exported.review_metadata, "Review confirmation must be explicitly preserved separately"


def test_export_rejects_stale_version_even_when_session_cached_old_workspace(preview_ai_context, preview_settings):
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    with context.session_factory.begin() as stale:
        cached = stale.get(PaperWorkspace, context.workspace_id)
        assert cached.version == 2
        with context.session_factory.begin() as editor:
            editor.get(PaperWorkspace, context.workspace_id).version = 3
        with pytest.raises(workspace_export.WorkspaceExportConflictError, match="version"):
            _export(stale, parent, application_id, preview_settings, version=2)


def test_export_refuses_unrepresentable_science_with_all_paths(preview_ai_context, preview_settings):
    from app.structures.models import Structure
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    with context.session_factory.begin() as session:
        session.scalar(select(Evidence)).reviewer_note = "Evidence contradicts the claimed relation"
        structure = session.scalar(select(Structure))
        structure.smiles = None
        structure.molfile = None
        structure.status = StructureStatus.UNRESOLVED
        session.get(PaperWorkspace, context.workspace_id).version = 3
    with context.session_factory.begin() as session:
        with pytest.raises(workspace_export.WorkspaceExportUnrepresentableError) as caught:
            _export(session, parent, application_id, preview_settings, version=3)
    assert any("reviewer_note" in issue["path"] for issue in caught.value.issues)
    assert any("structure" in issue["path"] for issue in caught.value.issues)


def test_export_rejects_different_parent_and_source_drift(preview_ai_context, preview_settings):
    from app.ai_prefill.assistance_contracts import with_computed_hashes
    from app.catalog.models import PaperSource
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    wrong = with_computed_hashes(parent.model_copy(update={"candidate_id": "wrong:parent"}))
    with context.session_factory.begin() as session:
        with pytest.raises(workspace_export.WorkspaceExportConflictError, match="parent"):
            _export(session, wrong, application_id, preview_settings)
    with context.session_factory.begin() as session:
        session.scalar(select(PaperSource)).byte_size += 1
    with context.session_factory.begin() as session:
        with pytest.raises(workspace_export.WorkspaceExportConflictError, match="Source"):
            _export(session, parent, application_id, preview_settings)


def test_export_holds_workspace_lock_until_callers_transaction_finishes(preview_ai_context, preview_settings):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    with context.session_factory.begin() as exporting:
        exported = _export(exporting, parent, application_id, preview_settings)
        with context.session_factory.begin() as editing:
            editing.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                editing.scalar(select(PaperWorkspace).where(PaperWorkspace.id == context.workspace_id).with_for_update())
    assert exported.workspace_version == 2
    with context.session_factory.begin() as editing:
        row = editing.scalar(select(PaperWorkspace).where(PaperWorkspace.id == context.workspace_id).with_for_update())
        row.version = 3


def test_export_does_not_silently_lose_bibliography_clearing(preview_ai_context, preview_settings):
    from app.papers.models import Paper
    context = preview_ai_context
    with context.session_factory.begin() as session:
        session.get(Paper, context.paper_id).doi = "10.1021/acs.jmedchem.4c00001"
    parent, application_id = _apply(context, preview_settings)
    with context.session_factory.begin() as session:
        session.get(Paper, context.paper_id).doi = None
        session.get(PaperWorkspace, context.workspace_id).version = 3
    with context.session_factory.begin() as session:
        with pytest.raises(workspace_export.WorkspaceExportUnrepresentableError, match="bibliography/doi"):
            _export(session, parent, application_id, preview_settings, version=3)


@pytest.fixture
def second_preview(postgresql_database_url, tmp_path):
    """Reuse isolated provisioning fixtures for a genuinely new instance."""
    from contextlib import contextmanager
    from . import conftest as preview_fixtures
    root = tmp_path / "second-preview"
    root.mkdir()
    with contextmanager(preview_fixtures.preview_database_url.__wrapped__)(postgresql_database_url) as url:
        with contextmanager(preview_fixtures.preview_session_factory.__wrapped__)(url) as factory:
            settings = preview_fixtures.preview_settings.__wrapped__(factory, url, root)
            context = preview_fixtures.preview_ai_context.__wrapped__(factory, settings)
            yield context, settings


def test_child_reapplies_to_fresh_preview_without_losing_duplicate_assays(
    preview_ai_context, preview_settings, second_preview,
):
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    actor = Principal(context.reviewer_id, UserRole.REVIEWER)
    with context.session_factory.begin() as session:
        existing = session.scalar(select(Activity))
        CompoundService().update_compound(session, compound_id=existing.compound_id,
            expected_version=2, actor=actor, updates={"description": "Verified against the table"})
        ActivityService().create_activity(session, compound_id=existing.compound_id,
            expected_version=3, actor=actor, evidence_id=existing.evidence_id,
            assay_name=existing.assay_name, metric=existing.metric,
            operator=existing.operator, value=existing.value, unit=existing.unit,
            context_value=existing.context)
    with context.session_factory.begin() as session:
        exported = _export(session, parent, application_id, preview_settings, version=4)
    fresh, fresh_settings = second_preview
    assert fresh_settings.preview_instance_id != preview_settings.preview_instance_id
    with fresh.session_factory.begin() as session:
        applied = PreviewApplicationService(settings=fresh_settings).apply(
            session, instance_id=fresh_settings.preview_instance_id,
            idempotency_key="human-child-fresh", candidate=exported.candidate,
            validation_report=validate_candidate(exported.candidate), actor_id=fresh.admin_id,
            paper_id=fresh.paper_id, workspace_id=fresh.workspace_id,
            expected_workspace_version=1,
        )
        assert applied.applied
    with fresh.session_factory() as session:
        rows = session.scalars(select(Activity)).all()
        assert len(rows) == 2
        assert rows[0].value == rows[1].value == Decimal("12.5")
        compound = session.scalar(select(Compound).where(Compound.compound_label == "Compound 18"))
        assert compound.description == "Verified against the table"
        assert all(row.compound_id == compound.id for row in rows)
        evidence = session.scalar(select(Evidence))
        assert all(row.evidence_id == evidence.id for row in rows)


def test_export_maps_new_human_lineage_evidence_and_locator_refs(preview_ai_context, preview_settings):
    from app.evidence.models import EdgeEvidenceLink, EvidenceKind, EvidenceRole
    from app.lineages.models import Lineage, LineageEdge, LineageMember
    from app.structure_images.models import StructureSourceImage
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    with context.session_factory.begin() as session:
        first, second = session.scalars(select(Compound).order_by(Compound.sort_order)).all()
        scope = {"paper_id": context.paper_id, "workspace_id": context.workspace_id}
        lineage = Lineage(**scope, lineage_label="Human pathway", lineage_type="synthesis", sort_order=1)
        evidence = Evidence(**scope, kind=EvidenceKind.TEXT, page_number=1,
            quoted_text="A human-located passage.", source_sha256=parent.source.source_sha256)
        session.add_all([lineage, evidence])
        session.flush()
        edge = LineageEdge(**scope, lineage_id=lineage.id, parent_compound_id=first.id,
            child_compound_id=second.id, relation_type="lead_optimization",
            modification_summary="Additional evidence confirms this transformation", review_status="draft")
        session.add_all([
            LineageMember(**scope, lineage_id=lineage.id, compound_id=first.id, role="root"),
            LineageMember(**scope, lineage_id=lineage.id, compound_id=second.id, role="terminal", sort_order=1)])
        session.flush()
        session.add(edge)
        session.flush()
        session.add_all([
            EdgeEvidenceLink(**scope, edge_id=edge.id, evidence_id=evidence.id, role=EvidenceRole.CONTEXTUAL),
            StructureSourceImage(**scope, compound_id=second.id,
                source_sha256=parent.source.source_sha256, page_number=2,
                x0=Decimal("0.1"), y0=Decimal("0.1"), x1=Decimal("0.2"), y1=Decimal("0.2"),
                source_context="Human selected image", label="Compound 18")])
        session.get(PaperWorkspace, context.workspace_id).version = 3
    with context.session_factory.begin() as session:
        first_export = _export(session, parent, application_id, preview_settings, version=3)
    with context.session_factory.begin() as session:
        second_export = _export(session, parent, application_id, preview_settings, version=3)
    payload = first_export.candidate.payload
    human_lineage = next(row for row in payload.lineages if row.lineage_label == "Human pathway")
    human_evidence = next(row for row in payload.evidence if row.quoted_text == "A human-located passage.")
    human_locator = next(row for row in payload.structure_locators if row.source_context == "Human selected image")
    assert human_lineage.lineage_type == "synthesis"
    assert human_lineage.ref.startswith("human:lineage:")
    assert human_lineage.edges[0].ref.startswith("human:edge:")
    assert human_evidence.ref.startswith("human:evidence:")
    assert human_locator.ref.startswith("human:locator:")
    assert human_locator.compound_ref == "compound:18"
    assert any(link.edge_ref == human_lineage.edges[0].ref and link.evidence_ref == human_evidence.ref
        and link.role == "contextual" for link in payload.edge_evidence_links)
    assert first_export.candidate.hashes.payload_sha256 == second_export.candidate.hashes.payload_sha256


def test_export_preserves_hints_and_explicit_clearing(preview_ai_context, preview_settings):
    from app.lineages.models import LineageEdge
    from app.lineages.service import LineageService
    context = preview_ai_context
    raw = complete_payload()
    for row in [raw['compounds'][0], raw['activities'][0], raw['lineages'][0]['edges'][0]]:
        row['review_hint'] = 'Source-supported but pairing needs checking'
    parent, application_id = _apply(context, preview_settings, raw)
    with context.session_factory.begin() as session:
        first = _export(session, parent, application_id, preview_settings)
    assert first.candidate.payload.compounds[0].review_hint == raw['compounds'][0]['review_hint']
    assert first.candidate.payload.activities[0].review_hint == raw['activities'][0]['review_hint']
    assert first.candidate.payload.lineages[0].edges[0].review_hint == raw['lineages'][0]['edges'][0]['review_hint']
    actor = Principal(context.reviewer_id, UserRole.REVIEWER)
    with context.session_factory.begin() as session:
        edge = session.scalar(select(LineageEdge))
        LineageService().update_edge(session, edge_id=edge.id, expected_version=2,
            actor=actor, updates={'review_hint': None})
    with context.session_factory.begin() as session:
        second = _export(session, parent, application_id, preview_settings, version=3)
    assert second.candidate.payload.lineages[0].edges[0].review_hint is None
    assert second.candidate.payload.compounds[0].review_hint
    assert parent.payload.lineages[0].edges[0].review_hint


def test_highlights_roundtrip_as_draft_with_separate_review_metadata(preview_ai_context, preview_settings):
    from app.compounds.models import CompoundHighlight
    from app.ai_prefill.assistance_verification import verify_application_receipt
    from app.ai_prefill.preview_models import ApplicationReceipt
    payload = complete_payload()
    payload['compound_highlights'] = [{'ref':'highlight:start', 'compound_ref':payload['compounds'][0]['ref'],
        'evidence_ref':payload['evidence'][0]['ref'], 'role':'study_start', 'scope':'Series A', 'rationale':'Synthetic author statement',
        'review_hint':'Verify attribution'}]
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings, payload)
    with context.session_factory.begin() as session:
        row = session.scalar(select(CompoundHighlight))
        assert row.review_status == 'draft' and row.created_by_kind == 'ai'
        receipt = session.scalar(select(ApplicationReceipt).where(ApplicationReceipt.application_id == application_id))
        assert verify_application_receipt(session, receipt).status == 'committed'
        exported = _export(session, parent, application_id, preview_settings)
        assert exported.candidate.payload.compound_highlights == parent.payload.compound_highlights
        assert any(x.get('path') == 'compound_highlights/highlight:start' and x.get('review_status') == 'draft' for x in exported.review_metadata)
        assert str(row.id) in exported.entity_refs
        assert 'review_status' not in exported.candidate.payload.model_dump(mode='json')['compound_highlights'][0]
