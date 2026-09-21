from datetime import UTC, datetime
from functools import lru_cache
import hashlib

import fitz

import pytest
from sqlalchemy import select

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    CandidateRecipe,
    ProducerProvenance,
    SourceIdentity,
    with_computed_hashes,
)
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.preview_application import (
    PreviewApplicationConflictError,
    PreviewApplicationService,
)
from app.ai_prefill.preview_models import ApplicationReceipt
from app.ai_prefill.contracts import AiPrefillPayload

from .test_apply import AiContext, _queue
from .test_contract import complete_payload


@lru_cache
def preview_pdf_bytes() -> bytes:
    with fitz.open() as document:
        for number in range(12):
            page = document.new_page(width=300, height=300)
            page.insert_text((30, 80), "Lead 1 was optimized to compound 18.", fontsize=10)
            page.draw_rect(fitz.Rect(35, 90, 110, 155), color=(0, 0, 0))
        return document.tobytes(no_new_id=True)


def make_candidate(payload: AiPrefillPayload) -> CandidateEnvelope:
    return with_computed_hashes(
        CandidateEnvelope(
            envelope_version=1,
            candidate_id="candidate:preview-v1",
            experiment_id="experiment:preview",
            source=SourceIdentity(
                paper_key="LT-JMC-2024-67-05-AI1",
                source_sha256=hashlib.sha256(preview_pdf_bytes()).hexdigest(),
                byte_size=len(preview_pdf_bytes()),
                page_count=12,
            ),
            producer=ProducerProvenance(
                kind="local",
                engine="test",
                engine_version="preview-v1",
                generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            recipe=CandidateRecipe(guide_version="guide-v1"),
            payload=payload,
        )
    )


def test_preview_application_writes_receipt_and_replays_by_idempotency_key(
    preview_ai_context: AiContext,
    preview_settings,
) -> None:
    candidate = make_candidate(AiPrefillPayload.model_validate(complete_payload()))
    report = validate_candidate(candidate)
    run_id = _queue(preview_ai_context)
    instance_id = preview_settings.preview_instance_id

    with preview_ai_context.session_factory.begin() as session:
        result = PreviewApplicationService(settings=preview_settings).apply(
            session,
            instance_id=instance_id,
            idempotency_key="preview-request-1",
            candidate=candidate,
            validation_report=report,
            actor_id=preview_ai_context.admin_id,
            paper_id=preview_ai_context.paper_id,
            workspace_id=preview_ai_context.workspace_id,
            run_id=run_id,
            expected_workspace_version=1,
        )
        assert result.applied
        assert not result.idempotent
        application_id = result.receipt.application_id

    with preview_ai_context.session_factory.begin() as session:
        replay = PreviewApplicationService(settings=preview_settings).apply(
            session,
            instance_id=instance_id,
            idempotency_key="preview-request-1",
            candidate=candidate,
            validation_report=report,
            actor_id=preview_ai_context.admin_id,
            paper_id=preview_ai_context.paper_id,
            workspace_id=preview_ai_context.workspace_id,
            run_id=run_id,
            expected_workspace_version=1,
        )
        assert replay.idempotent
        assert replay.receipt.application_id == application_id
        assert session.scalar(select(ApplicationReceipt.application_id)) == application_id


def test_preview_application_rejects_same_key_with_different_request(
    preview_ai_context: AiContext,
    preview_settings,
) -> None:
    candidate = make_candidate(AiPrefillPayload.model_validate(complete_payload()))
    report = validate_candidate(candidate)
    run_id = _queue(preview_ai_context)
    instance_id = preview_settings.preview_instance_id

    with preview_ai_context.session_factory.begin() as session:
        PreviewApplicationService(settings=preview_settings).apply(
            session,
            instance_id=instance_id,
            idempotency_key="preview-request-1",
            candidate=candidate,
            validation_report=report,
            actor_id=preview_ai_context.admin_id,
            paper_id=preview_ai_context.paper_id,
            workspace_id=preview_ai_context.workspace_id,
            run_id=run_id,
            expected_workspace_version=1,
        )

    changed = make_candidate(
        AiPrefillPayload.model_validate(
            {**complete_payload(), "bibliography": {"title": "changed"}}
        )
    )
    changed_report = validate_candidate(changed)
    with preview_ai_context.session_factory.begin() as session:
        with pytest.raises(PreviewApplicationConflictError):
            PreviewApplicationService(settings=preview_settings).apply(
                session,
                instance_id=instance_id,
                idempotency_key="preview-request-1",
                candidate=changed,
                validation_report=changed_report,
                actor_id=preview_ai_context.admin_id,
                paper_id=preview_ai_context.paper_id,
                workspace_id=preview_ai_context.workspace_id,
                run_id=run_id,
                expected_workspace_version=1,
            )


def _request(context, settings):
    candidate = make_candidate(AiPrefillPayload.model_validate(complete_payload()))
    return dict(instance_id=settings.preview_instance_id, idempotency_key="pinned-pdf",
                candidate=candidate, validation_report=validate_candidate(candidate),
                actor_id=context.admin_id, workspace_id=context.workspace_id,
                expected_workspace_version=1)


def test_apply_verifies_actual_pdf_before_scientific_writes(preview_ai_context, preview_settings):
    from app.ai_prefill.assistance_verification import PreviewApplicationValidationError
    from app.compounds.models import Compound
    from sqlalchemy import func
    source = preview_settings.source_roots["source_pdfs"] / "volume67 issue5/ai-paper.pdf"
    source.write_bytes(b"%PDF-1.7 replaced")
    with pytest.raises(PreviewApplicationValidationError, match="Source"):
        with preview_ai_context.session_factory.begin() as session:
            PreviewApplicationService(settings=preview_settings).apply(session, **_request(preview_ai_context, preview_settings))
    with preview_ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Compound)) == 0
        assert session.scalar(select(func.count()).select_from(ApplicationReceipt)) == 0


def test_apply_materializes_crop_from_pinned_pdf_even_when_disk_replaced(preview_ai_context, preview_settings, monkeypatch):
    import app.ai_prefill.preview_application as application
    from app.structure_images.models import StructureSourceImage, CropStatus
    from app.assets.models import Asset
    from app.assets.storage import LocalAssetStore
    original_verify = application.verify_candidate_for_application
    source = preview_settings.source_roots["source_pdfs"] / "volume67 issue5/ai-paper.pdf"
    def replace_after_validation(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        source.write_bytes(b"replaced after verification")
        return result
    monkeypatch.setattr(application, "verify_candidate_for_application", replace_after_validation)
    with preview_ai_context.session_factory.begin() as session:
        result = application.PreviewApplicationService(settings=preview_settings).apply(session, **_request(preview_ai_context, preview_settings))
        assert result.applied
        image = session.scalar(select(StructureSourceImage))
        assert image.crop_status == CropStatus.READY
        asset = session.get(Asset, image.crop_asset_id)
        path = LocalAssetStore(preview_settings.asset_root).path_for(asset.storage_key)
        assert path.read_bytes().startswith(b"\x89PNG")


def test_apply_outer_rollback_removes_generated_crop_files(preview_ai_context, preview_settings):
    from app.compounds.models import Compound
    from sqlalchemy import func
    with pytest.raises(RuntimeError, match="force outer rollback"):
        with preview_ai_context.session_factory.begin() as session:
            PreviewApplicationService(settings=preview_settings).apply(session, **_request(preview_ai_context, preview_settings))
            assert list(preview_settings.asset_root.rglob("*.png"))
            raise RuntimeError("force outer rollback")
    assert not list(preview_settings.asset_root.rglob("*.png"))
    with preview_ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Compound)) == 0
        assert session.scalar(select(func.count()).select_from(ApplicationReceipt)) == 0


def test_apply_requires_explicit_existing_workspace_version(preview_ai_context, preview_settings):
    from app.ai_prefill.assistance_verification import PreviewApplicationValidationError
    request = _request(preview_ai_context, preview_settings)
    request.pop("expected_workspace_version")
    with pytest.raises(PreviewApplicationValidationError, match="expected_workspace_version"):
        with preview_ai_context.session_factory.begin() as session:
            PreviewApplicationService(settings=preview_settings).apply(session, **request)


def test_replay_rejects_changed_expected_workspace_version(preview_ai_context, preview_settings):
    request = _request(preview_ai_context, preview_settings)
    service = PreviewApplicationService(settings=preview_settings)
    with preview_ai_context.session_factory.begin() as session:
        service.apply(session, **request)
    request["expected_workspace_version"] = 2
    with pytest.raises(PreviewApplicationConflictError):
        with preview_ai_context.session_factory.begin() as session:
            service.apply(session, **request)


@pytest.mark.parametrize("field,value", [("byte_size", 12345), ("page_count", 13)])
def test_apply_checks_pdf_metadata_even_when_candidate_matches_database(
    preview_ai_context, preview_settings, field, value,
):
    from app.ai_prefill.assistance_verification import PreviewApplicationValidationError
    from app.assets.models import Asset
    from app.catalog.models import PaperSource
    from app.papers.models import Paper
    request = _request(preview_ai_context, preview_settings)
    original = request["candidate"]
    request["candidate"] = with_computed_hashes(original.model_copy(update={
        "source": original.source.model_copy(update={field: value}), "hashes": None,
    }))
    request["validation_report"] = validate_candidate(request["candidate"])
    with preview_ai_context.session_factory.begin() as session:
        paper = session.get(Paper, preview_ai_context.paper_id)
        source = session.get(PaperSource, paper.source_id)
        asset = session.get(Asset, source.asset_id)
        setattr(source, field, value)
        setattr(asset, field, value)
    with pytest.raises(PreviewApplicationValidationError, match="byte integrity"):
        with preview_ai_context.session_factory.begin() as session:
            PreviewApplicationService(settings=preview_settings).apply(session, **request)


def test_commit_response_loss_replays_receipt_without_pdf_or_second_write(preview_ai_context, preview_settings):
    from app.compounds.models import Compound
    from app.ai_prefill.models import AiExtractionRun
    from app.workspaces.models import PaperWorkspace
    from sqlalchemy import func
    request = _request(preview_ai_context, preview_settings)
    service = PreviewApplicationService(settings=preview_settings)
    with pytest.raises(ConnectionError, match="response lost"):
        with preview_ai_context.session_factory.begin() as session:
            result = service.apply(session, **request)
            application_id = result.receipt.application_id
        raise ConnectionError("response lost after database commit")
    # Recovery exports the committed receipt; it must not repeat crop/AI work.
    source = preview_settings.source_roots["source_pdfs"] / "volume67 issue5/ai-paper.pdf"
    source.unlink()
    with preview_ai_context.session_factory.begin() as session:
        replay = service.apply(session, **request)
        assert replay.idempotent and not replay.applied
        assert replay.receipt.application_id == application_id
        assert session.scalar(select(func.count()).select_from(Compound)) == 2
        assert session.scalar(select(func.count()).select_from(AiExtractionRun)) == 1
        assert session.get(PaperWorkspace, preview_ai_context.workspace_id).version == 2
    assert len(list((preview_settings.asset_root / "crop").rglob("*.png"))) == 1


def test_concurrent_same_request_commits_once(preview_ai_context, preview_settings):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import func
    from app.ai_prefill.models import AiExtractionRun
    from app.compounds.models import Compound
    request = _request(preview_ai_context, preview_settings)
    barrier = Barrier(2)
    def apply_once():
        barrier.wait(timeout=10)
        with preview_ai_context.session_factory.begin() as session:
            result = PreviewApplicationService(settings=preview_settings).apply(session, **request)
            return result.receipt.application_id, result.applied, result.idempotent
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: apply_once(), range(2)))
    assert outcomes[0][0] == outcomes[1][0]
    assert sorted((value[1], value[2]) for value in outcomes) == [(False, True), (True, False)]
    with preview_ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ApplicationReceipt)) == 1
        assert session.scalar(select(func.count()).select_from(AiExtractionRun)) == 1
        assert session.scalar(select(func.count()).select_from(Compound)) == 2


def test_apply_rejects_invalid_pdf_with_forged_matching_metadata(preview_ai_context, preview_settings):
    from app.ai_prefill.assistance_verification import PreviewApplicationValidationError
    from app.assets.models import Asset
    from app.catalog.models import PaperSource
    from app.papers.models import Paper
    # Generic asset inspection permits a page-count fallback for historical
    # files. Preview apply requires a PDF that the renderer can actually open.
    content = b"%PDF-1.7\n" + b"/Type /Page\n" * 12
    digest = hashlib.sha256(content).hexdigest()
    source_path = preview_settings.source_roots["source_pdfs"] / "volume67 issue5/ai-paper.pdf"
    source_path.write_bytes(content)
    request = _request(preview_ai_context, preview_settings)
    original = request["candidate"]
    request["candidate"] = with_computed_hashes(original.model_copy(update={
        "source": original.source.model_copy(update={"source_sha256": digest, "byte_size": len(content)}),
        "hashes": None,
    }))
    request["validation_report"] = validate_candidate(request["candidate"])
    with preview_ai_context.session_factory.begin() as session:
        paper = session.get(Paper, preview_ai_context.paper_id)
        source = session.get(PaperSource, paper.source_id)
        asset = session.get(Asset, source.asset_id)
        source.sha256 = asset.sha256 = digest
        source.byte_size = asset.byte_size = len(content)
    with pytest.raises(PreviewApplicationValidationError, match="PDF"):
        with preview_ai_context.session_factory.begin() as session:
            PreviewApplicationService(settings=preview_settings).apply(session, **request)


def test_existing_assignment_requires_explicit_workspace_selection(preview_ai_context, preview_settings):
    request = _request(preview_ai_context, preview_settings)
    request.pop("workspace_id")
    request.pop("expected_workspace_version")
    with pytest.raises(PreviewApplicationConflictError, match="explicit workspace"):
        with preview_ai_context.session_factory.begin() as session:
            PreviewApplicationService(settings=preview_settings).apply(session, **request)


def test_receipt_captures_all_initial_bibliography_fields(preview_ai_context, preview_settings):
    with preview_ai_context.session_factory.begin() as session:
        result = PreviewApplicationService(settings=preview_settings).apply(session, **_request(preview_ai_context, preview_settings))
        assert result.receipt.initial_snapshot["paper"] == {
            "id": str(preview_ai_context.paper_id),
            "paper_key": "LT-JMC-2024-67-05-AI1",
            "title": "Extracted title before AI",
            "doi": None,
            "journal": "Journal of Medicinal Chemistry",
            "publication_year": 2024,
            "volume": "67",
            "issue": "5",
        }


def test_closing_uncommitted_session_removes_generated_crops(preview_ai_context, preview_settings):
    from sqlalchemy import func
    from app.compounds.models import Compound
    with preview_ai_context.session_factory() as session:
        PreviewApplicationService(settings=preview_settings).apply(session, **_request(preview_ai_context, preview_settings))
        assert list(preview_settings.asset_root.rglob("*.png"))
        # Session.close rolls back without invoking Session.after_rollback.
    assert not list(preview_settings.asset_root.rglob("*.png"))
    with preview_ai_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Compound)) == 0
        assert session.scalar(select(func.count()).select_from(ApplicationReceipt)) == 0


def test_preview_draws_rdkit_structure_depictions(preview_ai_context, preview_settings):
    from app.assets.models import Asset, AssetCategory
    from app.assets.storage import LocalAssetStore
    from app.structures.models import Structure
    with preview_ai_context.session_factory.begin() as session:
        PreviewApplicationService(settings=preview_settings).apply(session, **_request(preview_ai_context, preview_settings))
        structures = session.scalars(select(Structure)).all()
        assert len(structures) == 2
        for structure in structures:
            assert structure.depiction_asset_id is not None
            asset = session.get(Asset, structure.depiction_asset_id)
            assert asset.category is AssetCategory.RDKIT_STRUCTURE
            assert LocalAssetStore(preview_settings.asset_root).path_for(asset.storage_key).read_bytes().startswith(b"\x89PNG")


def test_rollback_preserves_preexisting_shared_depiction(preview_ai_context, preview_settings):
    from app.structures.service import StructureDrawingService
    from app.assets.models import Asset
    drawing = StructureDrawingService(preview_settings.asset_root)
    with preview_ai_context.session_factory.begin() as session:
        existing = drawing.draw(session, smiles="CCO")
        asset_id, path = existing.asset.id, existing.path
    original = path.read_bytes()
    with pytest.raises(RuntimeError):
        with preview_ai_context.session_factory.begin() as session:
            PreviewApplicationService(settings=preview_settings).apply(session, **_request(preview_ai_context, preview_settings))
            raise RuntimeError("rollback while reusing depiction")
    assert path.read_bytes() == original
    assert list(preview_settings.asset_root.rglob("*.png")) == [path]
    with preview_ai_context.session_factory() as session:
        assert session.get(Asset, asset_id) is not None
