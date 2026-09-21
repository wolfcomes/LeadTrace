"""Safe, offline-first AI-prefill CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
import tempfile
import sys
from pathlib import Path
from typing import Any

from app.ai_prefill.artifact_store import ArtifactStore
from app.ai_prefill.assistance_compare import compare_candidates
from app.ai_prefill.assistance_contracts import CandidateEnvelope
from app.ai_prefill.assistance_inputs import PrefillInputPackage, prepare_input_package
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.assistance_evaluation import build_evaluation_summary, validate_evaluation
from app.ai_prefill.assistance_contracts import Evaluation
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.workspace_export import export_candidate_revision
from leadtrace.ops.ai_prefill.preview_cleanup import PreviewCleanup
from leadtrace.ops.ai_prefill.preview_runtime import PreviewRuntime
from uuid import UUID


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str))


def _error(code: str, message: str, *, next_action: str | None = None) -> int:
    payload = {"ok": False, "code": code, "message": message}
    if next_action:
        payload["next_action"] = next_action
    _emit(payload)
    return 2


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m leadtrace.ops.ai_prefill")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check offline tool availability")
    contract = sub.add_parser("contract", help="export the Candidate contract")
    contract.add_argument("action", choices=["export"])
    contract.add_argument("--output", type=Path)
    prepare = sub.add_parser("input", help="prepare an AI input package")
    prepare.add_argument("action", choices=["prepare"])
    prepare.add_argument("--experiment-id", required=True)
    prepare.add_argument("--paper-key", required=True)
    prepare.add_argument("--source-sha256", required=True)
    prepare.add_argument("--byte-size", required=True, type=int)
    prepare.add_argument("--page-count", required=True, type=int)
    prepare.add_argument("--guide-version", default="guide-v1")
    prepare.add_argument("--source-path", type=Path)
    prepare.add_argument("--output", type=Path, required=True)
    candidate = sub.add_parser("candidate", help="import, validate, or compare candidates")
    candidate.add_argument("action", choices=["import", "validate", "coverage", "self-check", "compare", "export", "export-workspace"])
    candidate.add_argument("path", type=Path)
    candidate.add_argument("other", type=Path, nargs="?")
    candidate.add_argument("--artifact-root", type=Path)
    candidate.add_argument("--payload", type=Path)
    candidate.add_argument("--output", type=Path)
    candidate.add_argument("--candidate-id")
    candidate.add_argument("--evaluation-id")
    candidate.add_argument("--reviewer")
    candidate.add_argument("--profile", type=Path)
    candidate.add_argument("--application-id")
    candidate.add_argument("--expected-workspace-version", type=int)
    candidate.add_argument("--evaluation", type=Path)
    candidate.add_argument("--inventory", type=Path)
    candidate.add_argument("--self-review", type=Path)
    evaluation = sub.add_parser("evaluation", help="validate and summarize feedback")
    evaluation.add_argument("action", choices=["summary", "record"])
    evaluation.add_argument("path", type=Path)
    evaluation.add_argument("--profile", type=Path)
    evaluation.add_argument("--report", type=Path)
    evaluation.add_argument("--application-id")
    evaluation.add_argument("--expected-workspace-version", type=int)
    evaluation.add_argument("--evaluation-id")
    evaluation.add_argument("--reviewer")
    evaluation.add_argument("--decision", choices=["accepted", "needs_revision", "rejected"])
    evaluation.add_argument("--coverage", type=Path)
    evaluation.add_argument("--notes")
    evaluation.add_argument("--issue-code", action="append", default=[])
    evaluation.add_argument("--output", type=Path)
    evaluation.add_argument("--artifact-root", type=Path)
    preview = sub.add_parser("preview", help="create, run, inspect and clean Preview instances")
    preview.add_argument("action", choices=["create", "start", "status", "stop", "plan", "archive", "destroy"])
    preview.add_argument("--registry-root", type=Path)
    preview.add_argument("--archive-root", type=Path)
    preview.add_argument("--instance-id")
    preview.add_argument("--profile", type=Path)
    preview.add_argument("--provisioning-profile", type=Path)
    preview.add_argument("--manifest", type=Path)
    preview.add_argument("--source-root", type=Path)
    preview.add_argument("--origin")
    preview.add_argument("--commit")
    preview.add_argument("--lockfile-sha256")
    preview.add_argument("--receipts", type=Path)
    preview.add_argument("--confirm-instance")
    return parser


def _native_preview(args: argparse.Namespace) -> int:
    if args.action == "create":
        if not all((args.registry_root, args.instance_id, args.provisioning_profile,
                    args.manifest, args.source_root, args.origin, args.commit, args.lockfile_sha256)):
            return _error("PREVIEW_CREATE_OPTIONS_REQUIRED", "preview create requires --registry-root, --instance-id, --provisioning-profile, --manifest, --source-root, --origin, --commit and --lockfile-sha256")
    elif args.profile is None:
        return _error("PREVIEW_PROFILE_REQUIRED", "preview lifecycle requires --profile")
    if args.action == "archive" and args.archive_root is None:
        return _error("NATIVE_ARCHIVE_OPTIONS_REQUIRED", "native archive requires --archive-root")
    if args.action == "destroy" and not all((args.provisioning_profile, args.confirm_instance)):
        return _error("NATIVE_DESTROY_OPTIONS_REQUIRED", "native destroy requires --provisioning-profile and --confirm-instance")
    try:
        if args.action == "create":
            from app.ai_prefill.preview_provision import create_preview, load_provisioning_url
            result = create_preview(provisioning_url=load_provisioning_url(args.provisioning_profile),
                instance_id=UUID(args.instance_id), registry_root=args.registry_root,
                manifest_path=args.manifest, source_root=args.source_root, origin=args.origin,
                commit=args.commit, lockfile_sha256=args.lockfile_sha256)
            _emit({"ok": True, "state": "ready", **asdict(result),
                   "scope": "native_backend", "accounts": ["preview-admin", "preview-reviewer"],
                   "credentials_access": "Read credentials_path locally; never share it with Producer",
                   "login_api": result.origin + "/api/v1/auth/login"})
        elif args.action in {"archive", "destroy"}:
            from app.ai_prefill.preview_cleanup import archive_preview, destroy_preview
            from app.ai_prefill.preview_provision import load_provisioning_url
            result = (archive_preview(args.profile, args.archive_root) if args.action == "archive" else
                      destroy_preview(args.profile, provisioning_url=load_provisioning_url(args.provisioning_profile),
                                      confirm_instance=UUID(args.confirm_instance)))
            _emit({"ok": True, **result})
        elif args.action == "plan":
            from app.ai_prefill.preview_process import load_runtime_settings, status_preview
            settings = load_runtime_settings(args.profile)
            registry = json.loads(settings.preview_registry_path.read_text())
            _emit({"ok": True, "instance_id": str(settings.preview_instance_id),
                   "state": registry["state"], "database_name": registry["database_name"],
                   "asset_root": settings.asset_root, "source_root": settings.source_roots["source_pdfs"],
                   "preserved_artifact_root": settings.preview_artifact_root,
                   "archive_path": registry.get("archive_path"), "process": status_preview(args.profile)})
        else:
            from app.ai_prefill.preview_process import start_preview, status_preview, stop_preview
            operation = {"start": start_preview, "status": status_preview, "stop": stop_preview}[args.action]
            _emit({"ok": True, **operation(args.profile)})
        return 0
    except Exception:
        # Drivers, Pydantic and malformed profiles can include credentials in their errors.
        _emit({"ok": False, "code": "PREVIEW_OPERATION_FAILED",
               "message": "Preview operation failed; inspect the explicit profile, registry phase and local resources"})
    return 5


def _publish_output(path: Path, content: str) -> None:
    """Publish complete output without truncating an existing file on races."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".prefill-output-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _resume_evaluation(store, evaluation):
    from app.ai_prefill.artifact_store import ArtifactConflictError, _safe_id
    path = store.root / "experiments" / evaluation.experiment_id / "evaluations" / f"{_safe_id(evaluation.evaluation_id)}.json"
    if not path.exists() and not path.is_symlink():
        return evaluation
    saved = Evaluation.model_validate(store.read_json(path))
    if saved.model_dump(exclude={"created_at"}) != evaluation.model_dump(exclude={"created_at"}):
        raise ArtifactConflictError("evaluation ID already has different bound content")
    return saved


def _resume_candidate(store, candidate):
    from app.ai_prefill.artifact_store import ArtifactConflictError, _safe_id
    from app.ai_prefill.assistance_contracts import validate_declared_hashes
    path = store.root / "experiments" / candidate.experiment_id / "candidates" / _safe_id(candidate.candidate_id) / "candidate.json"
    if not path.exists() and not path.is_symlink():
        return candidate
    saved = CandidateEnvelope.model_validate(store.read_json(path))
    validate_declared_hashes(saved)
    excluded = {"hashes": True, "producer": {"generated_at"}}
    if saved.model_dump(exclude=excluded) != candidate.model_dump(exclude=excluded):
        raise ArtifactConflictError("candidate ID already has different bound content")
    return saved


def _export_workspace(args, parent):
    if not all((args.profile, args.application_id, args.expected_workspace_version,
                args.candidate_id, args.evaluation, args.reviewer, args.output)):
        return _error("WORKSPACE_EXPORT_OPTIONS_REQUIRED", "export-workspace requires --profile, --application-id, --expected-workspace-version, --candidate-id, --evaluation, --reviewer and --output")
    if args.output.exists() or args.output.is_symlink():
        return _error("OUTPUT_EXISTS", "candidate output already exists; choose a new path")
    from app.ai_prefill.preview_process import load_runtime_settings
    from app.ai_prefill.workspace_export import export_workspace_candidate
    from app.ai_prefill.assistance_contracts import computed_hashes
    from app.database import bootstrap_database
    evaluation = Evaluation.model_validate_json(args.evaluation.read_bytes())
    hashes = computed_hashes(parent)
    if (evaluation.candidate_id != parent.candidate_id or evaluation.experiment_id != parent.experiment_id
            or evaluation.candidate_sha256 != hashes.candidate_sha256
            or evaluation.payload_sha256 != hashes.payload_sha256
            or evaluation.source_sha256 != parent.source.source_sha256
            or not evaluation.validation_report_id or not evaluation.section_coverage
            or evaluation.applied_workspace_version is None
            or str(evaluation.application_id) != args.application_id
            or evaluation.workspace_version != args.expected_workspace_version):
        return _error("EVALUATION_IDENTITY_MISMATCH", "evaluation does not bind the selected parent/application/workspace version")
    validate_evaluation(evaluation, section_coverage=evaluation.section_coverage,
        reviewed_workspace_version=evaluation.workspace_version, applied_workspace_version=evaluation.applied_workspace_version)
    settings = load_runtime_settings(args.profile)
    from app.ai_prefill.assistance_contracts import ValidationReport
    from app.ai_prefill.artifact_store import _safe_id
    store = ArtifactStore(args.artifact_root or settings.preview_artifact_root)
    report_relative = Path("experiments") / parent.experiment_id / "validations" / f"{_safe_id(evaluation.validation_report_id)}.json"
    report_store = store
    if not (store.root / report_relative).exists() and store.root != settings.preview_artifact_root:
        report_store = ArtifactStore(settings.preview_artifact_root)
    report = ValidationReport.model_validate(report_store.read_json(report_store.root / report_relative))
    if (report.candidate_id != parent.candidate_id or report.experiment_id != parent.experiment_id
            or report.candidate_sha256 != hashes.candidate_sha256 or report.payload_sha256 != hashes.payload_sha256):
        return _error("EVALUATION_IDENTITY_MISMATCH", "evaluation report does not bind the selected parent")
    resources = bootstrap_database(settings)
    try:
        with resources.session_factory.begin() as session:
            result = export_workspace_candidate(session, parent, settings=settings,
                application_id=UUID(args.application_id), expected_workspace_version=args.expected_workspace_version,
                candidate_id=args.candidate_id, evaluation_id=evaluation.evaluation_id, reviewer=args.reviewer)
            from sqlalchemy import select
            from app.ai_prefill.preview_models import ApplicationReceipt
            receipt = session.scalar(select(ApplicationReceipt).where(
                ApplicationReceipt.application_id == UUID(args.application_id),
                ApplicationReceipt.instance_id == settings.preview_instance_id,
            ))
            applied_version = receipt.initial_snapshot.get("after_apply", {}).get("workspace_version")
            if evaluation.applied_workspace_version != applied_version:
                return _error("EVALUATION_IDENTITY_MISMATCH", "evaluation applied version differs from the actual application receipt")
            if result.snapshot_sha256 != evaluation.workspace_snapshot_sha256:
                return _error("EVALUATION_SNAPSHOT_MISMATCH", "workspace changed after evaluation")
        store = ArtifactStore(args.artifact_root or settings.preview_artifact_root)
        store.put_candidate(parent)
        store.put_validation(report)
        store.put_evaluation(evaluation)
        child = _resume_candidate(store, result.candidate)
        store.put_candidate(child)
        snapshot = {"snapshot": result.snapshot, "snapshot_sha256": result.snapshot_sha256,
                    "workspace_version": result.workspace_version, "entity_refs": result.entity_refs,
                    "review_metadata": result.review_metadata}
        store._atomic_write(store.root / "experiments" / parent.experiment_id / "snapshots" / f"{result.snapshot_sha256}.json",
                            json.dumps(snapshot, sort_keys=True, default=str).encode())
        _publish_output(args.output, child.model_dump_json(indent=2) + "\n")
        _emit({"ok": True, "candidate_id": result.candidate.candidate_id, "output": str(args.output),
               "snapshot_sha256": result.snapshot_sha256, "workspace_version": result.workspace_version})
        return 0
    finally:
        resources.close()


def _record_evaluation(args):
    if not all((args.profile, args.report, args.application_id, args.expected_workspace_version,
                args.evaluation_id, args.reviewer, args.decision, args.coverage, args.output)):
        return _error("EVALUATION_RECORD_OPTIONS_REQUIRED", "evaluation record requires --profile, --report, --application-id, --expected-workspace-version, --evaluation-id, --reviewer, --decision, --coverage and --output")
    if args.output.exists() or args.output.is_symlink():
        return _error("OUTPUT_EXISTS", "evaluation output already exists; choose a new path")
    from app.ai_prefill.preview_process import load_runtime_settings
    from app.ai_prefill.workspace_evaluation import record_workspace_evaluation
    from app.ai_prefill.assistance_contracts import ValidationReport
    from app.database import bootstrap_database
    candidate = CandidateEnvelope.model_validate_json(args.path.read_bytes())
    report = ValidationReport.model_validate_json(args.report.read_bytes())
    settings = load_runtime_settings(args.profile)
    resources = bootstrap_database(settings)
    try:
        with resources.session_factory.begin() as session:
            result = record_workspace_evaluation(session, settings=settings, candidate=candidate, report=report,
                application_id=UUID(args.application_id), expected_workspace_version=args.expected_workspace_version,
                evaluation_id=args.evaluation_id, reviewer=args.reviewer, decision=args.decision,
                section_coverage=_load_json(args.coverage), notes=args.notes, issue_codes=args.issue_code)
        store = ArtifactStore(args.artifact_root or settings.preview_artifact_root)
        store.put_candidate(candidate)
        store.put_validation(report)
        evaluation = _resume_evaluation(store, result.evaluation)
        store.put_evaluation(evaluation)
        store._atomic_write(store.root / "experiments" / candidate.experiment_id / "evaluation-snapshots" / f"{result.snapshot_sha256}.json",
                            json.dumps(result.snapshot, sort_keys=True, default=str).encode())
        _publish_output(args.output, json.dumps(evaluation.model_dump(mode="json"), sort_keys=True, indent=2) + "\n")
        _emit({"ok": True, "evaluation_id": result.evaluation.evaluation_id,
               "snapshot_sha256": result.snapshot_sha256, "output": str(args.output)})
        return 0
    finally:
        resources.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            _emit({"ok": True, "offline": True, "database": "not checked", "commands": ["contract export", "input prepare", "candidate import", "candidate validate", "candidate coverage", "candidate self-check", "candidate compare", "candidate export", "candidate export-workspace", "evaluation record", "evaluation summary", "preview create", "preview start", "preview status", "preview stop", "preview plan", "preview archive", "preview destroy"]})
            return 0
        if args.command == "contract":
            schema = CandidateEnvelope.model_json_schema()
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(schema, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _emit(schema)
            return 0
        if args.command == "input":
            from app.ai_prefill.assistance_contracts import SourceIdentity
            package = prepare_input_package(experiment_id=args.experiment_id, source=SourceIdentity(paper_key=args.paper_key, source_sha256=args.source_sha256, byte_size=args.byte_size, page_count=args.page_count), guide_version=args.guide_version, source_path=args.source_path)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(package.model_dump_json(indent=2) + "\n", encoding="utf-8")
            _emit({"ok": True, "output": str(args.output.resolve()), "package_version": package.package_version})
            return 0
        if args.command == "candidate":
            candidate = CandidateEnvelope.model_validate_json(args.path.read_text(encoding="utf-8"))
            if args.action == "self-check":
                from app.ai_prefill.assistance_coverage import CompoundInventory
                from app.ai_prefill.assistance_self_check import SourceSelfReview, self_check_candidate
                if args.inventory is None:
                    return _error("INVENTORY_REQUIRED", "candidate self-check requires --inventory")
                inputs = [args.path, args.inventory, args.self_review]
                if args.output and any(p and args.output.resolve() == p.resolve() for p in inputs):
                    return _error("INVALID_INPUT", "self-check output cannot overwrite an input file")
                inventory = CompoundInventory.model_validate_json(args.inventory.read_bytes())
                review = SourceSelfReview.model_validate_json(args.self_review.read_bytes()) if args.self_review else None
                report = self_check_candidate(candidate, inventory, candidate_file_bytes=args.path.read_bytes(), self_review=review)
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                _emit(report)
                return 4 if report["status"] == "needs_revision" else 0
            if args.action == "coverage":
                from app.ai_prefill.assistance_coverage import CompoundInventory, check_compound_coverage
                if args.inventory is None:
                    return _error("INVENTORY_REQUIRED", "candidate coverage requires --inventory")
                inventory = CompoundInventory.model_validate_json(args.inventory.read_bytes())
                report = check_compound_coverage(candidate, inventory)
                _emit(report)
                return 4 if report["status"] == "incomplete" else 0
            if args.action == "export-workspace":
                return _export_workspace(args, candidate)
            if args.action == "import":
                if args.artifact_root is None:
                    return _error("ARTIFACT_ROOT_REQUIRED", "candidate import requires --artifact-root")
                stored = ArtifactStore(args.artifact_root).put_candidate(candidate)
                _emit({"ok": True, "candidate_id": stored.candidate_id, "hashes": stored.hashes.model_dump(mode="json") if stored.hashes else None})
                return 0
            if args.action == "validate":
                report = validate_candidate(candidate)
                _emit(report.model_dump(mode="json"))
                return 4 if report.status == "invalid" else 0
            if args.other is None:
                if args.action != "export":
                    return _error("COMPARE_INPUT_REQUIRED", "candidate compare requires a second candidate path")
            if args.action == "compare":
                other = CandidateEnvelope.model_validate_json(args.other.read_text(encoding="utf-8"))
                _emit(compare_candidates(candidate, other))
                return 0
            if args.payload is None or args.output is None or not args.candidate_id or not args.evaluation_id or not args.reviewer:
                return _error("EXPORT_OPTIONS_REQUIRED", "candidate export requires --payload, --output, --candidate-id, --evaluation-id, and --reviewer")
            payload = AiPrefillPayload.model_validate_json(args.payload.read_text(encoding="utf-8"))
            child = export_candidate_revision(candidate, payload=payload, candidate_id=args.candidate_id, evaluation_id=args.evaluation_id, reviewer=args.reviewer)
            if args.output.exists() or args.output.is_symlink():
                return _error("OUTPUT_EXISTS", "candidate export requires a new output path; parent and existing candidates are preserved")
            _publish_output(args.output, child.model_dump_json(indent=2) + "\n")
            _emit({"ok": True, "candidate_id": child.candidate_id, "parent_candidate_id": child.parent_candidate_id, "output": str(args.output.resolve())})
            return 0
        if args.command == "evaluation":
            if args.action == "record":
                return _record_evaluation(args)
            evaluation = Evaluation.model_validate_json(args.path.read_text(encoding="utf-8"))
            if evaluation.section_coverage is None or evaluation.workspace_version is None or evaluation.applied_workspace_version is None:
                return _error("EVALUATION_CONTEXT_REQUIRED", "evaluation summary requires recorded section coverage and actual Workspace versions")
            validated = validate_evaluation(evaluation, section_coverage=evaluation.section_coverage,
                reviewed_workspace_version=evaluation.workspace_version, applied_workspace_version=evaluation.applied_workspace_version)
            print(build_evaluation_summary(validated), end="")
            return 0
        if args.command == "preview":
            if args.action in {"create", "start", "status", "stop"} or args.profile is not None:
                return _native_preview(args)
            if not all((args.instance_id, args.registry_root, args.archive_root)):
                return _error("PREVIEW_CLEANUP_OPTIONS_REQUIRED", "preview cleanup requires --instance-id, --registry-root and --archive-root")
            instance_id = UUID(args.instance_id)
            cleanup = PreviewCleanup(PreviewRuntime(args.registry_root), args.archive_root)
            if args.action == "plan":
                plan = cleanup.plan(instance_id)
                _emit({"ok": True, **asdict(plan)})
                return 0
            if args.action == "archive":
                receipts = {}
                if args.receipts is not None:
                    receipts = json.loads(args.receipts.read_text(encoding="utf-8"))
                path = cleanup.archive(instance_id, receipts=receipts)
                _emit({"ok": True, "instance_id": str(instance_id), "archive": str(path.resolve())})
                return 0
            if args.confirm_instance != str(instance_id):
                return _error("INSTANCE_CONFIRMATION_REQUIRED", "preview destroy requires --confirm-instance matching --instance-id")
            plan = cleanup.destroy(instance_id)
            _emit({"ok": True, "instance_id": plan.instance_id, "state": "archived", "asset_root": plan.asset_root})
            return 0
    except FileNotFoundError as error:
        return _error("INPUT_NOT_FOUND", str(error))
    except (ValueError, json.JSONDecodeError) as error:
        return _error("INVALID_INPUT", str(error))
    except Exception as error:
        if args.command in {"candidate", "evaluation"} and args.action in {"export-workspace", "record"}:
            _emit({"ok": False, "code": "PREVIEW_OPERATION_FAILED", "message": "Preview evaluation/export failed; inspect the explicit profile and bound artifact identities"})
            return 5
        print(str(error), file=sys.stderr)
        return 5
    return _error("UNAVAILABLE", "command is not implemented")


__all__ = ["build_parser", "main"]
