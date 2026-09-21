from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.ai_prefill.preview_identity import (
    PreviewIdentityError,
    PreviewMarkerData,
    PreviewRegistryData,
    require_preview_settings,
    verify_preview_identity,
)
from app.config import Settings


INSTANCE_ID = UUID("11111111-1111-4111-8111-111111111111")
BASELINE = "a" * 64


def registry() -> PreviewRegistryData:
    return PreviewRegistryData(
        instance_id=INSTANCE_ID,
        database_name="leadtrace_ap_example_preview",
        database_host="preview-postgres",
        database_port=5432,
        schema_revision="0026_ai_prefill_preview_receipts",
        baseline_sha256=BASELINE,
        asset_root=Path("/var/lib/leadtrace/preview/example/assets"),
        source_root=Path("/srv/leadtrace/source-pdfs"),
        artifact_root=Path("/var/lib/leadtrace/preview/example/artifacts"),
    )


def marker() -> PreviewMarkerData:
    return PreviewMarkerData(
        instance_id=INSTANCE_ID,
        baseline_sha256=BASELINE,
        schema_revision="0026_ai_prefill_preview_receipts",
    )


def test_preview_settings_require_explicit_isolated_roots() -> None:
    settings = Settings(
        environment="preview",
        database_url="postgresql+psycopg://preview:secret@preview-postgres/leadtrace_ap_example_preview",
        asset_root="/var/lib/leadtrace/preview/example/assets",
        source_roots={"source_pdfs": "/srv/leadtrace/source-pdfs"},
        preview_artifact_root="/var/lib/leadtrace/preview/example/artifacts",
        preview_registry_path="/var/lib/leadtrace/registry/registry.json",
        preview_instance_id=str(INSTANCE_ID),
        preview_baseline_sha256=BASELINE,
    )

    require_preview_settings(settings)


def test_preview_settings_do_not_turn_production_into_preview() -> None:
    settings = Settings(environment="development")

    with pytest.raises(PreviewIdentityError, match="preview environment"):
        require_preview_settings(settings)


def test_marker_registry_and_runtime_identity_must_match() -> None:
    settings = Settings(
        environment="preview",
        database_url="postgresql+psycopg://preview:secret@preview-postgres/leadtrace_ap_example_preview",
        asset_root="/var/lib/leadtrace/preview/example/assets",
        source_roots={"source_pdfs": "/srv/leadtrace/source-pdfs"},
        preview_artifact_root="/var/lib/leadtrace/preview/example/artifacts",
        preview_registry_path="/var/lib/leadtrace/registry/registry.json",
        preview_instance_id=str(INSTANCE_ID),
        preview_baseline_sha256=BASELINE,
    )

    verify_preview_identity(
        settings,
        registry=registry(),
        marker=marker(),
        database_name="leadtrace_ap_example_preview",
        schema_revision="0026_ai_prefill_preview_receipts",
        asset_root=Path("/var/lib/leadtrace/preview/example/assets"),
    )

    with pytest.raises(PreviewIdentityError, match="database name"):
        verify_preview_identity(
            settings,
            registry=registry(),
            marker=marker(),
            database_name="leadtrace_production",
            schema_revision="0026_ai_prefill_preview_receipts",
            asset_root=Path("/var/lib/leadtrace/preview/example/assets"),
        )
