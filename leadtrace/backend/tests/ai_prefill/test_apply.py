from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from uuid import UUID

import fitz
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.activities.models import Activity
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.service import AiPrefillService
from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.compounds.models import Compound
from app.evidence.models import EdgeEvidenceLink, Evidence
from app.lineages.models import Lineage, LineageEdge, LineageMember
from app.papers.models import Paper, PaperCatalogState
from app.security.policies import Principal
from app.structure_images.models import CropStatus, StructureSourceImage
from app.structure_images.service import StructureSourceImageService
from app.structures.models import Structure, StructureInputMethod, StructureStatus
from app.structures.service import StructureService
from app.users.models import UserRole
from app.users.service import UserService
from app.workspaces.models import (
    ChangeActorKind,
    ChangeEvent,
    PaperSection,
    PaperSectionReview,
    PaperWorkspace,
    ReviewTask,
    WorkspaceState,
)

from .test_contract import complete_payload


@dataclass(frozen=True, slots=True)
class AiContext:
    session_factory: sessionmaker[Session]
    workspace_id: UUID
    paper_id: UUID
    reviewer_id: UUID
    admin_id: UUID


@pytest.fixture
def ai_context(auth_session_factory: sessionmaker[Session]) -> AiContext:
    return create_ai_context(auth_session_factory)


def create_ai_context(auth_session_factory: sessionmaker[Session]) -> AiContext:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="ai.prefill.admin",
            display_name="AI Prefill Admin",
            role=UserRole.ADMIN,
            initial_password="AI prefill Admin password 2026!",
        )
        reviewer = UserService().create_user(
            session,
            username="ai.prefill.reviewer",
            display_name="AI Prefill Reviewer",
            role=UserRole.REVIEWER,
            initial_password="AI prefill Reviewer password 2026!",
        )
        asset = Asset(
            storage_key="source/source_pdfs/volume67 issue5/ai-paper.pdf",
            original_filename="ai-paper.pdf",
            sha256="a" * 64,
            byte_size=12_345,
            mime_type="application/pdf",
            page_count=12,
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={},
        )
        session.add(asset)
        session.flush()
        source = PaperSource(
            asset_id=asset.id,
            source_root_key="source_pdfs",
            source_key="volume67 issue5/ai-paper.pdf",
            sha256=asset.sha256,
            byte_size=asset.byte_size,
            page_count=asset.page_count,
            integrity_state=PaperSourceIntegrityState.VERIFIED,
        )
        session.add(source)
        session.flush()
        paper = Paper(
            paper_key="LT-JMC-2024-67-05-AI1",
            source_id=source.id,
            title="Extracted title before AI",
            journal="Journal of Medicinal Chemistry",
            publication_year=2024,
            volume="67",
            issue="5",
            doi=None,
            catalog_state=PaperCatalogState.EXTRACTED,
        )
        session.add(paper)
        session.flush()
        task = ReviewTask(
            paper_id=paper.id,
            assigned_reviewer_id=reviewer.id,
            created_by_id=admin.id,
        )
        session.add(task)
        session.flush()
        workspace = PaperWorkspace(
            paper_id=paper.id,
            review_task_id=task.id,
            state=WorkspaceState.EDITING,
            version=1,
        )
        session.add(workspace)
        session.flush()
        session.add_all(
            [
                PaperSectionReview(
                    paper_id=paper.id,
                    workspace_id=workspace.id,
                    section_key=section,
                )
                for section in PaperSection
            ]
        )
        ids = (workspace.id, paper.id, reviewer.id, admin.id)
    return AiContext(auth_session_factory, *ids)


def _queue(context: AiContext) -> UUID:
    with context.session_factory.begin() as session:
        result = AiPrefillService().queue(
            session,
            workspace_id=context.workspace_id,
            requested_by_id=context.admin_id,
            engine="legacy_pipeline",
            engine_version="pilot-v1",
        )
        return result.run.id


def test_applies_complete_payload_with_ai_history_and_stable_structure(
    ai_context: AiContext,
    tmp_path: Path,
) -> None:
    run_id = _queue(ai_context)
    payload = AiPrefillPayload.model_validate(complete_payload())
    service = AiPrefillService()

    with ai_context.session_factory.begin() as session:
        result = service.apply(session, run_id=run_id, payload=payload)
        assert result.applied is True
        assert result.idempotent is False
        assert result.run.status is AiExtractionRunStatus.SUCCEEDED
        assert result.entity_map is not None
        assert result.entity_map["/compounds/compound:lead-1"]
        assert result.entity_map["/compounds/compound:lead-1/structure"]
        assert result.entity_map["/structure_locators/structure-image:lead-1"]
        assert result.entity_map["/evidence/evidence:scheme-2"]
        assert result.entity_map["/activities/0"]

    with ai_context.session_factory() as session:
        workspace = session.get(PaperWorkspace, ai_context.workspace_id)
        paper = session.get(Paper, ai_context.paper_id)
        compounds = session.scalars(
            select(Compound).order_by(Compound.sort_order)
        ).all()
        structures = session.scalars(select(Structure)).all()
        source_images = session.scalars(select(StructureSourceImage)).all()
        lineages = session.scalars(select(Lineage)).all()
        members = session.scalars(select(LineageMember)).all()
        edges = session.scalars(select(LineageEdge)).all()
        evidence = session.scalars(select(Evidence)).all()
        links = session.scalars(select(EdgeEvidenceLink)).all()
        activities = session.scalars(select(Activity)).all()
        events = session.scalars(
            select(ChangeEvent).order_by(ChangeEvent.occurred_at, ChangeEvent.id)
        ).all()
        assert workspace is not None and workspace.version == 2
        assert paper is not None and paper.title == "AI normalized lead optimization study"
        assert [compound.compound_label for compound in compounds] == [
            "Lead 1",
            "Compound 18",
        ]
        assert len(structures) == 2
        assert len(source_images) == 1
        assert all(
            source_image.crop_status is not CropStatus.PENDING
            for source_image in source_images
        )
        science_objects = [
            *compounds,
            *structures,
            *source_images,
            *lineages,
            *members,
            *edges,
            *evidence,
            *links,
            *activities,
        ]
        assert science_objects
        assert all(
            row.created_by_kind is ChangeActorKind.AI
            for row in science_objects
        )
        assert {event.entity_type for event in events} >= {
            "paper",
            "compound",
            "structure",
            "structure_source_image",
            "lineage",
            "lineage_member",
            "lineage_edge",
            "evidence",
            "edge_evidence_link",
            "activity",
        }
        assert events and all(
            event.actor_kind is ChangeActorKind.AI
            and event.actor_id is None
            and event.ai_run_id == run_id
            for event in events
        )
        science_events = [event for event in events if event.entity_type != "paper"]
        assert science_events and all(
            event.after_value is not None
            and event.after_value.get("created_by_kind") == "ai"
            for event in science_events
        )
        first_structure_id = structures[0].id
        first_compound_id = structures[0].compound_id

    with ai_context.session_factory.begin() as session:
        mutation = StructureService(tmp_path / "managed").upsert_structure(
            session,
            compound_id=first_compound_id,
            expected_version=2,
            actor=Principal(ai_context.reviewer_id, UserRole.REVIEWER),
            status=StructureStatus.REVIEWER_CONFIRMED,
            input_method=StructureInputMethod.MANUAL_SMILES,
            smiles="CCCO",
            molfile=None,
        )
        assert mutation.structure.id == first_structure_id
        assert mutation.workspace.version == 3


def test_reviewer_version_change_supersedes_entire_run(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    with ai_context.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, ai_context.workspace_id)
        assert workspace is not None
        workspace.version += 1
        session.add(
            ChangeEvent(
                paper_id=ai_context.paper_id,
                workspace_id=ai_context.workspace_id,
                entity_type="paper",
                entity_id=ai_context.paper_id,
                action="paper.update",
                before_value={"title": "Extracted title before AI"},
                after_value={"title": "Reviewer title"},
                actor_kind=ChangeActorKind.REVIEWER,
                actor_id=ai_context.reviewer_id,
                ai_run_id=None,
            )
        )

    with ai_context.session_factory.begin() as session:
        result = AiPrefillService().apply(
            session,
            run_id=run_id,
            payload=AiPrefillPayload.model_validate(complete_payload()),
        )
        assert result.applied is False
        assert result.run.status is AiExtractionRunStatus.SUPERSEDED

    with ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Compound)) == 0
        assert session.scalar(select(func.count()).select_from(Structure)) == 0


def test_apply_materializes_ai_structure_source_image_crop(
    ai_context: AiContext,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_pdfs"
    source_path = source_root / "volume67 issue5" / "ai-paper.pdf"
    source_path.parent.mkdir(parents=True)
    document = fitz.open()
    for page_number in range(1, 13):
        page = document.new_page(width=320, height=240)
        page.insert_text((36, 48), f"AI paper page {page_number}")
    document.save(source_path)
    document.close()
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    with ai_context.session_factory.begin() as session:
        paper = session.get(Paper, ai_context.paper_id)
        assert paper is not None
        source = session.get(PaperSource, paper.source_id)
        assert source is not None
        asset = session.get(Asset, source.asset_id)
        assert asset is not None
        source.sha256 = source_sha256
        source.byte_size = len(source_bytes)
        asset.sha256 = source_sha256
        asset.byte_size = len(source_bytes)

    run_id = _queue(ai_context)
    service = AiPrefillService(
        StructureSourceImageService(
            tmp_path / "managed",
            source_roots={"source_pdfs": source_root},
        )
    )
    with ai_context.session_factory.begin() as session:
        result = service.apply(
            session,
            run_id=run_id,
            payload=AiPrefillPayload.model_validate(complete_payload()),
        )
        assert result.applied is True

    with ai_context.session_factory() as session:
        source_image = session.scalar(select(StructureSourceImage))
        assert source_image is not None
        assert source_image.crop_status is CropStatus.READY
        assert source_image.crop_asset_id is not None
        crop_asset = session.get(Asset, source_image.crop_asset_id)
        assert crop_asset is not None
        assert crop_asset.mime_type == "image/png"


def test_late_payload_failure_does_not_leave_orphan_crop_file(
    ai_context: AiContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source_pdfs"
    source_path = source_root / "volume67 issue5" / "ai-paper.pdf"
    source_path.parent.mkdir(parents=True)
    document = fitz.open()
    for page_number in range(1, 13):
        page = document.new_page(width=320, height=240)
        page.insert_text((36, 48), f"AI paper page {page_number}")
    document.save(source_path)
    document.close()
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    with ai_context.session_factory.begin() as session:
        paper = session.get(Paper, ai_context.paper_id)
        assert paper is not None
        source = session.get(PaperSource, paper.source_id)
        assert source is not None
        asset = session.get(Asset, source.asset_id)
        assert asset is not None
        source.sha256 = source_sha256
        source.byte_size = len(source_bytes)
        asset.sha256 = source_sha256
        asset.byte_size = len(source_bytes)

    managed_root = tmp_path / "managed"
    service = AiPrefillService(
        StructureSourceImageService(
            managed_root,
            source_roots={"source_pdfs": source_root},
        )
    )

    def fail_late(_: Activity) -> dict[str, object]:
        raise RuntimeError("late activity validation failed")

    monkeypatch.setattr("app.ai_prefill.service.activity_snapshot", fail_late)
    run_id = _queue(ai_context)
    with ai_context.session_factory.begin() as session:
        result = service.apply(
            session,
            run_id=run_id,
            payload=AiPrefillPayload.model_validate(complete_payload()),
        )
        assert result.applied is False
        assert result.run.status is AiExtractionRunStatus.FAILED

    assert list(managed_root.rglob("*.png")) == []


def test_post_crop_snapshot_failure_does_not_leave_orphan_crop_file(
    ai_context: AiContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source_pdfs"
    source_path = source_root / "volume67 issue5" / "ai-paper.pdf"
    source_path.parent.mkdir(parents=True)
    document = fitz.open()
    for page_number in range(1, 13):
        page = document.new_page(width=320, height=240)
        page.insert_text((36, 48), f"AI paper page {page_number}")
    document.save(source_path)
    document.close()
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    with ai_context.session_factory.begin() as session:
        paper = session.get(Paper, ai_context.paper_id)
        assert paper is not None
        source = session.get(PaperSource, paper.source_id)
        assert source is not None
        asset = session.get(Asset, source.asset_id)
        assert asset is not None
        source.sha256 = source_sha256
        source.byte_size = len(source_bytes)
        asset.sha256 = source_sha256
        asset.byte_size = len(source_bytes)

    managed_root = tmp_path / "managed"
    service = AiPrefillService(
        StructureSourceImageService(
            managed_root,
            source_roots={"source_pdfs": source_root},
        )
    )

    def fail_after_crop(_: StructureSourceImage) -> dict[str, object]:
        raise RuntimeError("post-crop snapshot failed")

    monkeypatch.setattr("app.ai_prefill.service.source_image_snapshot", fail_after_crop)
    run_id = _queue(ai_context)
    with ai_context.session_factory.begin() as session:
        result = service.apply(
            session,
            run_id=run_id,
            payload=AiPrefillPayload.model_validate(complete_payload()),
        )
        assert result.applied is False
        assert result.run.status is AiExtractionRunStatus.FAILED

    assert list(managed_root.rglob("*.png")) == []


def test_outer_commit_failure_removes_new_crop_file(
    ai_context: AiContext,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_pdfs"
    source_path = source_root / "volume67 issue5" / "ai-paper.pdf"
    source_path.parent.mkdir(parents=True)
    document = fitz.open()
    for page_number in range(1, 13):
        page = document.new_page(width=320, height=240)
        page.insert_text((36, 48), f"AI paper page {page_number}")
    document.save(source_path)
    document.close()
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    with ai_context.session_factory.begin() as session:
        paper = session.get(Paper, ai_context.paper_id)
        assert paper is not None
        source = session.get(PaperSource, paper.source_id)
        assert source is not None
        asset = session.get(Asset, source.asset_id)
        assert asset is not None
        source.sha256 = source_sha256
        source.byte_size = len(source_bytes)
        asset.sha256 = source_sha256
        asset.byte_size = len(source_bytes)

    managed_root = tmp_path / "managed"
    service = AiPrefillService(
        StructureSourceImageService(
            managed_root,
            source_roots={"source_pdfs": source_root},
        )
    )
    run_id = _queue(ai_context)

    with ai_context.session_factory() as session:
        def fail_outer_commit(active_session: Session) -> None:
            if not active_session.in_nested_transaction():
                raise RuntimeError("outer commit failed")

        event.listen(session, "before_commit", fail_outer_commit)
        with pytest.raises(RuntimeError, match="outer commit failed"):
            with session.begin():
                result = service.apply(
                    session,
                    run_id=run_id,
                    payload=AiPrefillPayload.model_validate(complete_payload()),
                )
                assert result.applied is True

    assert list(managed_root.rglob("*.png")) == []


def test_invalid_source_locator_fails_without_partial_science_rows(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    raw = complete_payload()
    raw["structure_locators"][0]["page_number"] = 99  # type: ignore[index]

    with ai_context.session_factory.begin() as session:
        result = AiPrefillService().apply(
            session,
            run_id=run_id,
            payload=AiPrefillPayload.model_validate(raw),
        )
        assert result.applied is False
        assert result.run.status is AiExtractionRunStatus.FAILED
        assert result.run.error_summary == "AI payload failed source validation"

    with ai_context.session_factory() as session:
        paper = session.get(Paper, ai_context.paper_id)
        assert paper is not None and paper.title == "Extracted title before AI"
        for model in (
            Compound,
            Structure,
            StructureSourceImage,
            Lineage,
            LineageMember,
            LineageEdge,
            Evidence,
            EdgeEvidenceLink,
            Activity,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_retried_successful_run_is_idempotent(ai_context: AiContext) -> None:
    run_id = _queue(ai_context)
    payload = AiPrefillPayload.model_validate(complete_payload())
    service = AiPrefillService()
    with ai_context.session_factory.begin() as session:
        first = service.apply(session, run_id=run_id, payload=payload)
        assert first.applied is True
    with ai_context.session_factory.begin() as session:
        second = service.apply(session, run_id=run_id, payload=payload)
        assert second.applied is False
        assert second.idempotent is True
        assert second.run.status is AiExtractionRunStatus.SUCCEEDED

    with ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Compound)) == 2
        assert session.scalar(select(func.count()).select_from(Structure)) == 2
        assert session.scalar(select(func.count()).select_from(AiExtractionRun)) == 1


def test_ai_edge_without_evidence_is_saved_as_draft_and_listed_for_reviewer(ai_context):
    from app.lineages.models import LineageEdgeReviewStatus
    from app.lineages.service import LineageService
    raw = complete_payload()
    raw["evidence"] = []
    raw["edge_evidence_links"] = []
    raw["activities"] = []
    raw["structure_locators"] = []
    reasoning = "AI inference from series design: replace the lead substituent; verify manually"
    raw["lineages"][0]["edges"][0]["modification_summary"] = reasoning
    run_id = _queue(ai_context)
    with ai_context.session_factory.begin() as session:
        result = AiPrefillService().apply(session, run_id=run_id, payload=AiPrefillPayload.model_validate(raw))
        assert result.applied
    with ai_context.session_factory() as session:
        listing = LineageService().list_lineages(
            session, workspace_id=ai_context.workspace_id,
            actor=Principal(ai_context.reviewer_id, UserRole.REVIEWER),
        )
        edge = listing.records[0].edges[0]
        assert edge.review_status is LineageEdgeReviewStatus.DRAFT
        assert edge.created_by_kind is ChangeActorKind.AI
        assert edge.modification_summary == reasoning
        assert session.scalar(select(func.count()).select_from(Evidence)) == 0
        assert session.scalar(select(func.count()).select_from(EdgeEvidenceLink)) == 0


def test_ai_lineage_classification_survives_apply_and_snapshot(ai_context):
    from app.workspaces.snapshot import build_paper_snapshot
    payload_data = complete_payload()
    payload_data["lineages"][0]["lineage_type"] = "synthesis"
    payload = AiPrefillPayload.model_validate(payload_data)
    run_id = _queue(ai_context)
    with ai_context.session_factory.begin() as session:
        result = AiPrefillService().apply(session, run_id=run_id, payload=payload)
        assert result.applied
    with ai_context.session_factory() as session:
        lineage = session.scalar(select(Lineage))
        assert lineage.lineage_type == "synthesis"
        assert build_paper_snapshot(session, ai_context.workspace_id)["lineages"][0]["lineage_type"] == "synthesis"


def test_duplicate_source_occurrences_merge_without_losing_refs_or_annotations(ai_context):
    from copy import deepcopy
    raw=complete_payload();first=raw['structure_locators'][0]
    duplicate=deepcopy(first);duplicate.update(ref='duplicate-location',label='Alternate source label',source_context='Additional source explanation')
    raw['structure_locators'].append(duplicate)
    run_id=_queue(ai_context)
    with ai_context.session_factory.begin() as session:
        result=AiPrefillService().apply(session,run_id=run_id,payload=AiPrefillPayload.model_validate(raw))
        assert result.applied,(result.run.status,result.run.error_summary)
        assert result.entity_map['/structure_locators/'+first['ref']]==result.entity_map['/structure_locators/duplicate-location']
        rows=list(session.scalars(select(StructureSourceImage)))
        assert len(rows)==1
        assert 'Additional source explanation' in rows[0].source_context
        assert 'Alternate source label' in (rows[0].label or '')+(rows[0].source_context or '')
        assert result.delivery_notes[0]['code']=='DUPLICATE_STRUCTURE_OCCURRENCE_MERGED'
        assert session.scalar(select(func.count()).select_from(ChangeEvent).where(ChangeEvent.entity_type=='structure_source_image'))==1
