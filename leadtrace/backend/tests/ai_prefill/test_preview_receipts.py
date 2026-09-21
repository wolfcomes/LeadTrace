from __future__ import annotations

from sqlalchemy import UniqueConstraint

from app.ai_prefill.preview_models import ApplicationReceipt, PreviewMarker
from app.db.base import Base


def test_preview_receipt_schema_contains_application_identity_and_hashes() -> None:
    table = ApplicationReceipt.__table__

    assert {
        "instance_id",
        "application_id",
        "idempotency_key",
        "request_digest",
        "candidate_sha256",
        "payload_sha256",
        "source_sha256",
        "paper_id",
        "workspace_id",
        "run_id",
        "actor_id",
        "entity_map",
        "initial_snapshot",
        "committed_at",
    } <= set(table.c.keys())
    unique_sets = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("instance_id", "idempotency_key") in unique_sets


def test_preview_marker_is_registered_in_the_shared_model_registry() -> None:
    assert PreviewMarker.__tablename__ == "preview_markers"
    assert ApplicationReceipt.__tablename__ == "preview_application_receipts"
    assert Base.metadata.tables["preview_markers"] is PreviewMarker.__table__
    assert Base.metadata.tables["preview_application_receipts"] is ApplicationReceipt.__table__
