from __future__ import annotations

import json
import logging
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from app.assets.storage import AssetMimeMismatchError, LocalAssetStore
from app.config import Settings
from app.main import create_app
from app.security.ingestion import (
    ArchiveLimits,
    UnsafeArchiveError,
    UnsafeOutboundURLError,
    validate_outbound_url,
    validate_zip_archive,
)


def _settings(asset_root: Path, **updates: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": "postgresql+psycopg://leadtrace:test@database/leadtrace",
        "session_secret": "web-security-session-secret-more-than-thirty-two-characters",
        "allowed_hosts": ["testserver"],
        "asset_root": asset_root,
        "metrics_bearer_token": "metrics-token-with-more-than-thirty-two-characters",
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def _test_app(settings: Settings):
    return create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: None,
    )


def test_request_log_is_structured_and_redacts_secrets_and_paths(
    tmp_path: Path,
    caplog,
) -> None:
    marker = "cookie-token-that-must-not-appear"
    caplog.set_level(logging.INFO, logger="leadtrace.request")
    settings = _settings(tmp_path)

    with TestClient(_test_app(settings)) as client:
        response = client.get(
            "/health/live?next=/var/lib/leadtrace/assets/private.pdf",
            headers={
                "X-Request-ID": "security-log-001",
                "Cookie": f"leadtrace_session={marker}",
                "Authorization": f"Bearer {marker}",
            },
        )

    assert response.status_code == 200
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "leadtrace.request"
    ]
    assert records == [
        {
            "duration_ms": records[0]["duration_ms"],
            "event": "http_request",
            "method": "GET",
            "request_id": "security-log-001",
            "result": "success",
            "role": None,
            "route": "/health/live",
            "status_code": 200,
        }
    ]
    serialized = json.dumps(records)
    assert marker not in serialized
    assert "/var/lib/leadtrace" not in serialized


def test_metrics_are_separate_from_health_and_require_a_bearer_token(
    tmp_path: Path,
) -> None:
    token = "metrics-token-with-more-than-thirty-two-characters"
    settings = _settings(tmp_path, metrics_bearer_token=token)

    with TestClient(_test_app(settings)) as client:
        health = client.get("/health/live")
        anonymous = client.get("/internal/metrics")
        authorized = client.get(
            "/internal/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert health.status_code == 200
    assert "leadtrace_http_requests_total" not in health.text
    assert anonymous.status_code == 404
    assert authorized.status_code == 200
    assert authorized.headers["content-type"].startswith("text/plain")
    assert "leadtrace_http_requests_total" in authorized.text
    assert token not in authorized.text


def test_failed_request_log_uses_the_stable_redacted_error_code(
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger="leadtrace.request")
    settings = _settings(tmp_path)

    with TestClient(_test_app(settings)) as client:
        response = client.get(
            "/internal/metrics",
            headers={"X-Request-ID": "metrics-denied-001"},
        )

    assert response.status_code == 404
    record = next(
        json.loads(entry.message)
        for entry in caplog.records
        if entry.name == "leadtrace.request"
    )
    assert record["error_code"] == "RESOURCE_NOT_FOUND"


def test_mime_spoofing_is_rejected_from_content_signature(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "paper.pdf").write_bytes(b"\x89PNG\r\n\x1a\nnot-a-pdf")
    store = LocalAssetStore(tmp_path / "managed", source_roots={"import": source})

    with pytest.raises(AssetMimeMismatchError, match="PDF"):
        store.inspect("source/import/paper.pdf")


@pytest.mark.parametrize(
    "member_name",
    ["../escape.txt", "/absolute.txt", "a/b/c/d/e/deep.txt"],
)
def test_archive_gate_rejects_traversal_and_excessive_depth(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as handle:
        handle.writestr(member_name, b"payload")

    with pytest.raises(UnsafeArchiveError):
        validate_zip_archive(
            archive,
            ArchiveLimits(max_members=10, max_total_bytes=1024, max_depth=4),
        )


def test_archive_gate_rejects_member_count_and_expansion_size(tmp_path: Path) -> None:
    archive = tmp_path / "oversized.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as handle:
        handle.writestr("one.txt", b"a" * 700)
        handle.writestr("two.txt", b"b" * 700)

    with pytest.raises(UnsafeArchiveError, match="limit"):
        validate_zip_archive(
            archive,
            ArchiveLimits(max_members=1, max_total_bytes=1024, max_depth=4),
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://evidence.example/paper.pdf",
        "https://127.0.0.1/paper.pdf",
        "https://user:password@evidence.example/paper.pdf",
        "https://evidence.example:8443/paper.pdf",
        "https://evidence.example.attacker.invalid/paper.pdf",
    ],
)
def test_ssrf_gate_accepts_only_exact_allowlisted_https_hosts(url: str) -> None:
    with pytest.raises(UnsafeOutboundURLError):
        validate_outbound_url(url, allowed_hosts={"evidence.example"})

    assert (
        validate_outbound_url(
            "https://evidence.example/paper.pdf",
            allowed_hosts={"evidence.example"},
        ).geturl()
        == "https://evidence.example/paper.pdf"
    )


def test_nginx_lan_entrypoint_requires_tls_and_keeps_metrics_internal() -> None:
    config_path = Path(__file__).parents[3] / "deploy" / "nginx" / "nginx.conf"
    config = config_path.read_text(encoding="utf-8")

    assert "listen 8080 ssl;" in config
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in config
    assert "ssl_certificate /etc/nginx/tls/leadtrace.crt;" in config
    assert "ssl_certificate_key /etc/nginx/tls/leadtrace.key;" in config
    assert "Strict-Transport-Security" in config
    assert "location = /internal/metrics" in config
    assert "return 404;" in config
    assert "ws:" not in config
