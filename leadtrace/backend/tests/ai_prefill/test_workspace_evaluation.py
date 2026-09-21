from importlib import import_module, util

import pytest
from sqlalchemy import select

from app.ai_prefill.assistance_evaluation import SECTIONS, EvaluationValidationError
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.workspace_export import WorkspaceExportConflictError
from app.compounds.models import Compound
from app.compounds.service import CompoundService
from app.security.policies import Principal
from app.users.models import UserRole
from app.workspaces.models import PaperWorkspace
from app.workspaces.snapshot import canonical_snapshot_hash
from .test_workspace_db_export import _apply


def _record(session, parent, application_id, settings, *, version=2, decision="needs_revision", coverage=None, report=None):
    module_name = "app.ai_prefill.workspace_evaluation"
    assert util.find_spec(module_name) is not None, "database-bound Workspace evaluation is missing"
    return import_module(module_name).record_workspace_evaluation(
        session, settings=settings, candidate=parent,
        report=report or validate_candidate(parent, report_id="validation:review"),
        application_id=application_id, expected_workspace_version=version,
        evaluation_id="evaluation:bound", reviewer="reviewer:test", decision=decision,
        section_coverage=coverage or {section: "partial" for section in SECTIONS},
        notes="Automated checks found issues; human review still required.",
        issue_codes=["EVIDENCE_VISUAL_QUOTE"],
    )


def test_evaluation_binds_actual_application_source_report_and_snapshot(preview_ai_context, preview_settings):
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    with context.session_factory.begin() as session:
        result = _record(session, parent, application_id, preview_settings)
    value = result.evaluation
    assert value.candidate_sha256 == parent.hashes.candidate_sha256
    assert value.payload_sha256 == parent.hashes.payload_sha256
    assert value.source_sha256 == parent.source.source_sha256
    assert value.validation_report_id == "validation:review"
    assert value.application_id == application_id
    assert value.workspace_version == value.applied_workspace_version == 2
    assert value.workspace_snapshot_sha256 == result.snapshot_sha256 == canonical_snapshot_hash(result.snapshot)
    assert value.workspace_snapshot_id == f"sha256:{result.snapshot_sha256}"
    assert value.section_coverage == {section: "partial" for section in SECTIONS}
    assert value.decision == "needs_revision"


def test_accepted_requires_all_sections_and_unedited_applied_version(preview_ai_context, preview_settings):
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    complete = {section: "reviewed" for section in SECTIONS}
    with context.session_factory.begin() as session:
        with pytest.raises(EvaluationValidationError, match="coverage"):
            _record(session, parent, application_id, preview_settings, decision="accepted")
    with context.session_factory.begin() as session:
        accepted = _record(session, parent, application_id, preview_settings,
            decision="accepted", coverage=complete)
        assert accepted.evaluation.decision == "accepted"
    with context.session_factory.begin() as session:
        compound = session.scalar(select(Compound))
        CompoundService().update_compound(session, compound_id=compound.id,
            expected_version=2, actor=Principal(context.reviewer_id, UserRole.REVIEWER),
            updates={"description": "Corrected during review"})
    with context.session_factory.begin() as session:
        with pytest.raises(EvaluationValidationError, match="edited"):
            _record(session, parent, application_id, preview_settings, version=3,
                decision="accepted", coverage=complete)
    with context.session_factory.begin() as session:
        revised = _record(session, parent, application_id, preview_settings, version=3)
    assert revised.evaluation.workspace_version == 3
    assert revised.evaluation.applied_workspace_version == 2


def test_evaluation_refuses_wrong_report_and_stale_workspace(preview_ai_context, preview_settings):
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    wrong_report = validate_candidate(parent).model_copy(update={"candidate_sha256": "f" * 64})
    with context.session_factory.begin() as session:
        with pytest.raises(EvaluationValidationError, match="report"):
            _record(session, parent, application_id, preview_settings, report=wrong_report)
    with context.session_factory.begin() as session:
        with pytest.raises(WorkspaceExportConflictError, match="version"):
            _record(session, parent, application_id, preview_settings, version=1)


def test_needs_revision_can_describe_unrepresentable_human_workspace(preview_ai_context, preview_settings):
    from app.evidence.models import Evidence
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    with context.session_factory.begin() as session:
        session.scalar(select(Evidence)).reviewer_note = "This quote contradicts the proposed relationship"
        session.get(PaperWorkspace, context.workspace_id).version = 3
    with context.session_factory.begin() as session:
        result = _record(session, parent, application_id, preview_settings, version=3)
    assert result.evaluation.decision == "needs_revision"
    assert result.snapshot["evidence"][0]["reviewer_note"] == "This quote contradicts the proposed relationship"


def test_invalid_validation_report_cannot_support_accepted_decision(preview_ai_context, preview_settings):
    context = preview_ai_context
    parent, application_id = _apply(context, preview_settings)
    invalid = validate_candidate(parent).model_copy(update={"status": "invalid"})
    with context.session_factory.begin() as session:
        with pytest.raises(EvaluationValidationError, match="invalid"):
            _record(session, parent, application_id, preview_settings, decision="accepted",
                coverage={section: "reviewed" for section in SECTIONS}, report=invalid)
