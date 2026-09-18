from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_PATH = REPOSITORY_ROOT / "leadtrace" / "deploy" / "compose.yaml"
NGINX_PATH = REPOSITORY_ROOT / "leadtrace" / "deploy" / "nginx" / "nginx.conf"
NGINX_SECURITY_PATHS = (
    NGINX_PATH,
    REPOSITORY_ROOT / "leadtrace" / "deploy" / "nginx" / "nginx.native.conf",
    REPOSITORY_ROOT
    / "leadtrace"
    / "deploy"
    / "nginx"
    / "nginx.native-preflight.conf",
)
DOCKERFILE_PATH = REPOSITORY_ROOT / "leadtrace" / "backend" / "Dockerfile"


def _exact_location(configuration: str, path: str) -> str:
    marker = f"    location = {path} {{"
    start = configuration.index(marker)
    end = configuration.index("\n    }", start)
    return configuration[start : end + len("\n    }")]


def test_compose_runs_one_shot_migration_before_web_and_worker() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["migrate"]["command"] == [
        "python",
        "-m",
        "alembic",
        "-c",
        "alembic.ini",
        "upgrade",
        "head",
    ]
    assert services["migrate"]["restart"] == "no"
    assert services["web"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["worker"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["scheduler"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )


def test_nginx_replaces_untrusted_forwarded_for_header() -> None:
    nginx_configuration = NGINX_PATH.read_text(encoding="utf-8")

    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx_configuration
    assert "$proxy_add_x_forwarded_for" not in nginx_configuration
    assert "proxy_set_header X-Real-IP $remote_addr;" in nginx_configuration


def test_nginx_scopes_ketcher_csp_to_the_exact_html_entry() -> None:
    for path in NGINX_SECURITY_PATHS:
        configuration = path.read_text(encoding="utf-8")
        ketcher_location = _exact_location(configuration, "/ketcher.html")

        assert 'add_header X-Frame-Options "DENY" always;' in configuration
        assert "script-src 'self';" in configuration
        assert "frame-ancestors 'none'" in configuration

        assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in ketcher_location
        assert "script-src 'self' 'unsafe-eval'" in ketcher_location
        assert "worker-src 'self' blob:" in ketcher_location
        assert "frame-ancestors 'self'" in ketcher_location

        assert configuration.count("script-src 'self' 'unsafe-eval'") == 1
        assert configuration.count("worker-src 'self' blob:") == 1
        assert configuration.count('X-Frame-Options "SAMEORIGIN"') == 1


def test_backend_trusts_only_the_fixed_nginx_peer_for_client_ip_headers() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    nginx_backend = compose["services"]["nginx"]["networks"]["backend"]
    trusted_peers = compose["services"]["web"]["environment"][
        "LEADTRACE_TRUSTED_PROXY_ADDRESSES"
    ]
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert nginx_backend["ipv4_address"] == "172.30.97.10"
    assert trusted_peers == '["172.30.97.10"]'
    assert "--no-proxy-headers" in dockerfile
    assert "--forwarded-allow-ips" not in dockerfile


def test_web_mounts_source_pdfs_read_only_with_working_default() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    web = compose["services"]["web"]

    assert web["environment"]["LEADTRACE_SOURCE_ROOTS"] == (
        '${LEADTRACE_SOURCE_ROOTS:-{"source_pdfs":'
        '"/var/lib/leadtrace/source_pdfs"}}'
    )
    assert (
        "${LEADTRACE_SOURCE_PDFS_HOST_ROOT:-../../source_pdfs}:"
        "/var/lib/leadtrace/source_pdfs:ro"
    ) in web["volumes"]
