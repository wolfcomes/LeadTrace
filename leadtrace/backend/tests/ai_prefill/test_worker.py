from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.extractor import ProtectedPdfReference
from app.ai_prefill.legacy_adapter import LegacyPipelineAdapter
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.service import AiPrefillService
from app.ai_prefill.worker_service import execute_ai_prefill_run
from app.compounds.models import Compound
from app.workspaces.models import ChangeEvent

from .test_apply import AiContext, ai_context  # noqa: F401
from .test_contract import complete_payload


def test_celery_registers_and_dispatches_ai_prefill_task(monkeypatch) -> None:
    from app.ai_prefill.celery_tasks import (
        AI_PREFILL_TASK_NAME,
        dispatch_ai_prefill_run,
        execute_ai_prefill,
    )
    from app.worker import celery_app

    captured: list[list[str]] = []
    monkeypatch.setattr(
        execute_ai_prefill,
        "apply_async",
        lambda *, args: captured.append(args),
    )
    run_id = UUID("10000000-0000-4000-8000-000000000099")
    dispatch_token = UUID("20000000-0000-4000-8000-000000000099")

    dispatch_ai_prefill_run(run_id, dispatch_token)

    assert AI_PREFILL_TASK_NAME in celery_app.tasks
    assert captured == [[str(run_id), str(dispatch_token)]]
    assert celery_app.conf.beat_schedule["reconcile-ai-prefill-runs"] == {
        "task": "leadtrace.ai_prefill.reconcile",
        "schedule": 30.0,
    }


class StubExtractor:
    engine = "stub"
    engine_version = "test-v1"

    def __init__(self, payload: AiPrefillPayload | Exception) -> None:
        self.payload = payload
        self.references: list[ProtectedPdfReference] = []

    def extract(self, source: ProtectedPdfReference) -> AiPrefillPayload:
        self.references.append(source)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _queue(context: AiContext, *, engine: str = "stub") -> UUID:
    with context.session_factory.begin() as session:
        return AiPrefillService().queue(
            session,
            workspace_id=context.workspace_id,
            requested_by_id=context.admin_id,
            engine=engine,
            engine_version="test-v1",
        ).run.id


def test_worker_extracts_from_logical_pdf_reference_and_applies_atomically(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    extractor = StubExtractor(AiPrefillPayload.model_validate(complete_payload()))

    report = execute_ai_prefill_run(
        ai_context.session_factory,
        run_id=run_id,
        extractor=extractor,
    )

    assert report == {
        "run_id": str(run_id),
        "status": "succeeded",
        "applied": True,
        "idempotent": False,
    }
    assert len(extractor.references) == 1
    source = extractor.references[0]
    assert source.paper_id == ai_context.paper_id
    assert source.source_root_key == "source_pdfs"
    assert source.source_key == "volume67 issue5/ai-paper.pdf"
    assert source.sha256 == "a" * 64
    assert source.page_count == 12
    assert not hasattr(source, "storage_key")
    assert not hasattr(source, "physical_path")


def test_worker_failure_records_safe_error_without_science_rows(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)

    report = execute_ai_prefill_run(
        ai_context.session_factory,
        run_id=run_id,
        extractor=StubExtractor(RuntimeError("provider credential leaked-secret")),
    )

    assert report == {
        "run_id": str(run_id),
        "status": "failed",
        "applied": False,
        "idempotent": False,
    }
    with ai_context.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None
        assert run.status is AiExtractionRunStatus.FAILED
        assert run.error_summary == "AI extraction failed"
        assert "credential" not in run.error_summary
        assert session.scalar(select(func.count()).select_from(Compound)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_stale_dispatch_token_exits_before_extraction(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    extractor = StubExtractor(AiPrefillPayload.model_validate(complete_payload()))
    stale_token = UUID("30000000-0000-4000-8000-000000000099")

    report = execute_ai_prefill_run(
        ai_context.session_factory,
        run_id=run_id,
        dispatch_token=stale_token,
        extractor=extractor,
    )

    assert report == {
        "run_id": str(run_id),
        "status": "queued",
        "applied": False,
        "idempotent": True,
    }
    assert extractor.references == []


def test_duplicate_delivery_of_claimed_run_exits_before_extraction(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    with ai_context.session_factory.begin() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None and run.dispatch_token is not None
        token = run.dispatch_token
        run.status = AiExtractionRunStatus.RUNNING
    extractor = StubExtractor(AiPrefillPayload.model_validate(complete_payload()))

    report = execute_ai_prefill_run(
        ai_context.session_factory,
        run_id=run_id,
        dispatch_token=token,
        extractor=extractor,
    )

    assert report == {
        "run_id": str(run_id),
        "status": "running",
        "applied": False,
        "idempotent": True,
    }
    assert extractor.references == []


def test_worker_refreshes_heartbeat_while_extractor_runs(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    with ai_context.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None and run.dispatch_token is not None
        dispatch_token = run.dispatch_token
    started = Event()
    release = Event()

    class BlockingExtractor(StubExtractor):
        def extract(self, source: ProtectedPdfReference) -> AiPrefillPayload:
            self.references.append(source)
            started.set()
            assert release.wait(timeout=3)
            assert not isinstance(self.payload, Exception)
            return self.payload

    extractor = BlockingExtractor(
        AiPrefillPayload.model_validate(complete_payload())
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            execute_ai_prefill_run,
            ai_context.session_factory,
            run_id=run_id,
            dispatch_token=dispatch_token,
            extractor=extractor,
            heartbeat_interval=timedelta(milliseconds=20),
        )
        try:
            assert started.wait(timeout=2)
            with ai_context.session_factory() as session:
                claimed = session.get(AiExtractionRun, run_id)
                assert claimed is not None and claimed.heartbeat_at is not None
                claimed_heartbeat = claimed.heartbeat_at
            deadline = monotonic() + 2
            refreshed = False
            while monotonic() < deadline:
                with ai_context.session_factory() as session:
                    current = session.get(AiExtractionRun, run_id)
                    assert current is not None
                    if (
                        current.heartbeat_at is not None
                        and current.heartbeat_at > claimed_heartbeat
                    ):
                        refreshed = True
                        break
                release.wait(timeout=0.02)
            assert refreshed is True
        finally:
            release.set()

        assert future.result(timeout=3)["status"] == "succeeded"


def test_recovered_delivery_failure_cannot_overwrite_new_lease(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    with ai_context.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None and run.dispatch_token is not None
        stale_token = run.dispatch_token
    started = Event()
    release = Event()

    class FailingBlockingExtractor(StubExtractor):
        def extract(self, source: ProtectedPdfReference) -> AiPrefillPayload:
            self.references.append(source)
            started.set()
            assert release.wait(timeout=3)
            raise RuntimeError("stale worker failed")

    extractor = FailingBlockingExtractor(
        AiPrefillPayload.model_validate(complete_payload())
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            execute_ai_prefill_run,
            ai_context.session_factory,
            run_id=run_id,
            dispatch_token=stale_token,
            extractor=extractor,
            heartbeat_interval=timedelta(milliseconds=20),
        )
        assert started.wait(timeout=2)
        replacement_token = uuid4()
        with ai_context.session_factory.begin() as session:
            run = session.get(AiExtractionRun, run_id)
            assert run is not None
            run.status = AiExtractionRunStatus.QUEUED
            run.dispatch_token = replacement_token
            run.started_at = None
            run.heartbeat_at = None
        release.set()
        report = future.result(timeout=3)

    assert report == {
        "run_id": str(run_id),
        "status": "queued",
        "applied": False,
        "idempotent": True,
    }
    with ai_context.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None
        assert run.status is AiExtractionRunStatus.QUEUED
        assert run.dispatch_token == replacement_token


def test_unexpected_apply_failure_safely_terminates_current_delivery(
    ai_context: AiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _queue(ai_context)
    extractor = StubExtractor(AiPrefillPayload.model_validate(complete_payload()))

    def fail_apply(*_: object, **__: object) -> object:
        raise RuntimeError("database credential leaked-secret")

    monkeypatch.setattr(AiPrefillService, "apply", fail_apply)

    report = execute_ai_prefill_run(
        ai_context.session_factory,
        run_id=run_id,
        extractor=extractor,
    )

    assert report == {
        "run_id": str(run_id),
        "status": "failed",
        "applied": False,
        "idempotent": False,
    }
    with ai_context.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None
        assert run.status is AiExtractionRunStatus.FAILED
        assert run.error_summary == "AI prefill execution failed"
        assert "credential" not in run.error_summary


def test_compose_mounts_ai_inputs_read_only_with_working_defaults() -> None:
    compose_path = Path(__file__).parents[3] / "deploy" / "compose.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    worker = compose["services"]["worker"]

    assert worker["environment"]["LEADTRACE_SOURCE_ROOTS"] == (
        '${LEADTRACE_SOURCE_ROOTS:-{"source_pdfs":"/var/lib/leadtrace/source_pdfs"}}'
    )
    assert (
        "${LEADTRACE_AI_PREFILL_LEGACY_HOST_ROOT:-../../source_pdfs/"
        "\u5206\u5b50\u4fee\u6539\u63d0\u53d6_2024_JMC}:/var/lib/leadtrace/legacy:ro"
        in worker["volumes"]
    )
    assert (
        "${LEADTRACE_SOURCE_PDFS_HOST_ROOT:-../../source_pdfs}:"
        "/var/lib/leadtrace/source_pdfs:ro"
        in worker["volumes"]
    )


def _write_legacy_fixture(root: Path) -> None:
    manifest = root / "01_manifest"
    output = root / "09_paper_review" / "auto_fill"
    manifest.mkdir(parents=True)
    output.mkdir(parents=True)
    (manifest / "all_volume67_papers.csv").write_text(
        "paper_id,source_folder,source_pdf,filename,filename_year,title_guess,file_size_bytes\n"
        "legacy001,volume67 issue5,source_pdfs/volume67 issue5/paper.pdf,paper.pdf,2024,Legacy title,1000\n",
        encoding="utf-8",
    )
    (output / "compound_entities.csv").write_text(
        "compound_entity_id,paper_id,doi,lineage_ids,display_label,normalized_label,preferred_name,entity_origin,entity_role,compound_object_ids,canonical_smiles,structure_status,structure_source_type,structure_source_file,structure_source_locator,structure_review_status,review_status,annotation_version\n"
        "CMP-1,legacy001,10.1021/example,LINEAGE-1,Lead 1,lead-1,Starting lead,in_paper,root_template,--,CCO,complete_structure_resolved,machine_readable_structure_source,si.csv,row=2,structure_confirmed,unreviewed,v1\n"
        "CMP-2,legacy001,10.1021/example,LINEAGE-1,Compound 2,compound-2,Optimized compound,in_paper,derived_compound,--,CCN,complete_structure_resolved,machine_readable_structure_source,si.csv,row=3,structure_confirmed,unreviewed,v1\n"
        "CMP-3,legacy001,10.1021/example,LINEAGE-1,Candidate 3,candidate-3,--,in_paper,derived_compound,--,--,unresolved,--,--,--,needs_confirmation,unreviewed,v1\n",
        encoding="utf-8",
    )
    (output / "confirmed_compound_structures.csv").write_text(
        "confirmed_structure_id,paper_id,compound_entity_id,compound_label,normalized_label,canonical_isomeric_smiles,confirmation_status,structure_review_status,structure_source_type,structure_source_file,structure_source_locator,reconstruction_method,scaffold_smiles,r_group_assignments,attachment_mapping,rdkit_version,accepted_work_row_id\n"
        "CONF-1,legacy001,CMP-1,Lead 1,lead-1,CCO,structure_confirmed,structure_confirmed,machine_readable_structure_source,si.csv,row=2,direct_source_structure,--,--,--,2023.09.6,WORK-1\n"
        "CONF-2,legacy001,CMP-2,Compound 2,compound-2,CCN,structure_confirmed,structure_confirmed,machine_readable_structure_source,si.csv,row=3,direct_source_structure,--,--,--,2023.09.6,WORK-2\n",
        encoding="utf-8",
    )
    (output / "compound_lineage_edges.csv").write_text(
        "lineage_edge_id,lineage_id,paper_id,doi,root_template_entity_id,root_template_label,parent_entity_id,parent_label,derived_entity_id,derived_label,parent_role,iteration_depth,modification_site,from_group,to_group,relation_type,relation_status,relation_confidence,evidence_ids,pair_eligible,review_status,review_note,annotation_version\n"
        "EDGE-1,LINEAGE-1,legacy001,10.1021/example,CMP-1,Lead 1,CMP-1,Lead 1,CMP-2,Compound 2,root_template,1,site,OH,NH2,substitution,text_explicit,high,EVID-1,yes,unreviewed,--,v1\n"
        "EDGE-2,LINEAGE-1,legacy001,10.1021/example,CMP-1,Lead 1,CMP-2,Compound 2,CMP-3,Candidate 3,lead,2,site,NH2,F,substitution,unresolved,low,EVID-2,no,unreviewed,--,v1\n",
        encoding="utf-8",
    )
    (output / "compound_lineage_evidence.csv").write_text(
        "lineage_evidence_id,lineage_edge_id,lineage_id,paper_id,doi,evidence_type,page,source_locator,evidence_text,source_object_ids,evidence_strength,review_status,annotation_version\n"
        "EVID-1,EDGE-1,LINEAGE-1,legacy001,10.1021/example,text,4,Results; Scheme 1,Lead 1 was optimized to Compound 2.,--,text_explicit,unreviewed,v1\n"
        "EVID-2,EDGE-2,LINEAGE-1,legacy001,10.1021/example,text,99,Unknown,Unsafe candidate.,--,unresolved_context,unreviewed,v1\n",
        encoding="utf-8",
    )
    (output / "compound_activities.csv").write_text(
        "activity_id,paper_id,doi,compound_entity_id,compound_label,target,assay,metric,value,unit,qualifier,comparator,page,source_locator,evidence_text,review_status,annotation_version\n"
        "ACT-1,legacy001,10.1021/example,CMP-2,Compound 2,target,Cell potency,IC50,12.5,nM,=,--,5,Table 1,IC50 = 12.5 nM,unreviewed,v1\n"
        "ACT-2,legacy001,10.1021/example,CMP-2,Compound 2,target,Cell potency,IC50,12.5 plus or minus 2,nM,=,--,--,SI table,Unsupported scalar,unreviewed,v1\n",
        encoding="utf-8",
    )


def test_legacy_adapter_emits_only_deterministic_supported_records(
    tmp_path: Path,
) -> None:
    _write_legacy_fixture(tmp_path)
    adapter = LegacyPipelineAdapter(tmp_path)

    payload = adapter.extract(
        ProtectedPdfReference(
            paper_id=UUID("10000000-0000-4000-8000-000000000001"),
            source_root_key="source_pdfs",
            source_key="volume67 issue5/paper.pdf",
            sha256="a" * 64,
            page_count=12,
        )
    )

    assert payload.bibliography.doi == "10.1021/example"
    assert [item.ref for item in payload.compounds] == ["CMP-1", "CMP-2"]
    assert [item.structure.smiles for item in payload.compounds] == ["CCO", "CCN"]
    assert payload.structure_locators == []
    assert len(payload.lineages) == 1
    assert [member.role for member in payload.lineages[0].members] == [
        "root",
        "terminal",
    ]
    assert [edge.ref for edge in payload.lineages[0].edges] == ["EDGE-1"]
    assert len(payload.evidence) == 2
    assert payload.edge_evidence_links[0].role == "supports"
    assert len(payload.activities) == 1
    assert payload.activities[0].evidence_ref == "activity-evidence:ACT-1"
    dumped = payload.model_dump(mode="json")
    assert "confidence" not in str(dumped).casefold()
    assert "candidate" not in str(dumped).casefold()


@pytest.mark.parametrize("pair_eligible", ["yes", "no"])
@pytest.mark.parametrize("relation_status", ["figure_explicit", "ai_inferred"])
def test_legacy_adapter_keeps_resolved_edge_without_text_evidence(tmp_path, pair_eligible, relation_status):
    _write_legacy_fixture(tmp_path)
    output = tmp_path / "09_paper_review" / "auto_fill"
    edges = output / "compound_lineage_edges.csv"
    edges.write_text(edges.read_text().replace("text_explicit,high,EVID-1,yes", f"{relation_status},high,--,{pair_eligible}"))
    (output / "compound_activities.csv").unlink()
    payload = LegacyPipelineAdapter(tmp_path).extract(ProtectedPdfReference(
        paper_id=UUID("10000000-0000-4000-8000-000000000001"),
        source_root_key="source_pdfs", source_key="volume67 issue5/paper.pdf",
        sha256="a" * 64, page_count=12,
    ))
    assert [item.ref for item in payload.compounds] == ["CMP-1", "CMP-2"]
    assert [edge.ref for edge in payload.lineages[0].edges] == ["EDGE-1"]
    assert payload.edge_evidence_links == []
    assert payload.evidence == []
    assert "AI-proposed" in payload.lineages[0].edges[0].modification_summary
    assert "no linked Evidence" in payload.lineages[0].edges[0].modification_summary
    assert "OH -> NH2" in payload.lineages[0].edges[0].modification_summary


@pytest.mark.parametrize("status", ["unresolved", "rejected", "invalid", ""])
def test_legacy_adapter_does_not_promote_unknown_or_rejected_relations(tmp_path, status):
    _write_legacy_fixture(tmp_path)
    output = tmp_path / "09_paper_review" / "auto_fill"
    edges = output / "compound_lineage_edges.csv"
    edges.write_text(edges.read_text().replace("text_explicit,high,EVID-1,yes", f"{status},high,EVID-1,yes"))
    payload = LegacyPipelineAdapter(tmp_path).extract(ProtectedPdfReference(
        paper_id=UUID("10000000-0000-4000-8000-000000000001"),
        source_root_key="source_pdfs", source_key="volume67 issue5/paper.pdf",
        sha256="a" * 64, page_count=12,
    ))
    assert payload.lineages == []


def test_legacy_adapter_keeps_human_rejection_out_of_graph(tmp_path):
    _write_legacy_fixture(tmp_path)
    edges = tmp_path / "09_paper_review" / "auto_fill" / "compound_lineage_edges.csv"
    edges.write_text(edges.read_text().replace("EVID-1,yes,unreviewed", "EVID-1,yes,rejected"))
    payload = LegacyPipelineAdapter(tmp_path).extract(ProtectedPdfReference(
        paper_id=UUID("10000000-0000-4000-8000-000000000001"),
        source_root_key="source_pdfs", source_key="volume67 issue5/paper.pdf",
        sha256="a" * 64, page_count=12,
    ))
    assert payload.lineages == []
