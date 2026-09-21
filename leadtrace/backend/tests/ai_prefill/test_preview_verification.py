from types import SimpleNamespace
from uuid import uuid4

from app.ai_prefill.assistance_verification import verify_application_receipt
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.preview_models import ApplicationReceipt
from app.workspaces.models import PaperWorkspace, WorkspaceState


class FakeSession:
    def __init__(self, rows: dict[tuple[type[object], object], object], event_count: int):
        self.rows = rows
        self.event_count = event_count

    def get(self, model: type[object], identity: object) -> object | None:
        return self.rows.get((model, identity))

    def scalar(self, _statement: object) -> int:
        return self.event_count


def receipt(*, workspace_id, paper_id, run_id, version: int, entity_map=None):
    return ApplicationReceipt(
        instance_id=uuid4(),
        application_id=uuid4(),
        idempotency_key="request-1",
        request_digest="a" * 64,
        candidate_sha256="b" * 64,
        payload_sha256="c" * 64,
        source_sha256="d" * 64,
        paper_id=paper_id,
        workspace_id=workspace_id,
        run_id=run_id,
        actor_id=uuid4(),
        entity_map=entity_map or {},
        initial_snapshot={
            "after_apply": {
                "workspace_version": version,
                "ai_event_count": 1,
            }
        },
    )


def rows(workspace_id, paper_id, run_id, version: int):
    workspace = SimpleNamespace(
        id=workspace_id,
        paper_id=paper_id,
        version=version,
        state=WorkspaceState.EDITING,
    )
    run = SimpleNamespace(
        id=run_id,
        paper_id=paper_id,
        workspace_id=workspace_id,
        status=AiExtractionRunStatus.SUCCEEDED,
    )
    return {
        (PaperWorkspace, workspace_id): workspace,
        (AiExtractionRun, run_id): run,
    }


def test_verify_receipt_reports_committed_when_state_matches_receipt() -> None:
    workspace_id, paper_id, run_id = uuid4(), uuid4(), uuid4()
    value = receipt(
        workspace_id=workspace_id,
        paper_id=paper_id,
        run_id=run_id,
        version=2,
    )

    result = verify_application_receipt(
        FakeSession(rows(workspace_id, paper_id, run_id, 2), event_count=1),
        value,
    )

    assert result.status == "committed"
    assert result.details["workspace_version"] == 2


def test_verify_receipt_distinguishes_manual_edits_from_apply_failure() -> None:
    workspace_id, paper_id, run_id = uuid4(), uuid4(), uuid4()
    value = receipt(
        workspace_id=workspace_id,
        paper_id=paper_id,
        run_id=run_id,
        version=2,
    )

    result = verify_application_receipt(
        FakeSession(rows(workspace_id, paper_id, run_id, 3), event_count=1),
        value,
    )

    assert result.status == "changed_since_apply"


def test_verify_receipt_reports_integrity_failure_for_missing_entity() -> None:
    workspace_id, paper_id, run_id = uuid4(), uuid4(), uuid4()
    missing_id = uuid4()
    value = receipt(
        workspace_id=workspace_id,
        paper_id=paper_id,
        run_id=run_id,
        version=2,
        entity_map={"/compounds/c1": str(missing_id)},
    )

    result = verify_application_receipt(
        FakeSession(rows(workspace_id, paper_id, run_id, 2), event_count=1),
        value,
    )

    assert result.status == "integrity_failure"
    assert result.details["missing_entity"] == "/compounds/c1"
