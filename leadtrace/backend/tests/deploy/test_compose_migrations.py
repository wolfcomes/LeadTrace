from __future__ import annotations

import json
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
NATIVE_NGINX_SECURITY_PATHS = NGINX_SECURITY_PATHS[1:]
DOCKERFILE_PATH = REPOSITORY_ROOT / "leadtrace" / "backend" / "Dockerfile"
CUTOVER_RUNBOOK_PATH = (
    REPOSITORY_ROOT / "leadtrace" / "ops" / "runbooks" / "cutover.md"
)
FRONTEND_PACKAGE_PATH = REPOSITORY_ROOT / "leadtrace" / "frontend" / "package.json"


def _exact_location(configuration: str, path: str) -> str:
    marker = f"    location = {path} {{"
    start = configuration.index(marker)
    end = configuration.index("\n    }", start)
    return configuration[start : end + len("\n    }")]


def _prefix_location(configuration: str, path: str) -> str:
    marker = f"    location {path} {{"
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


def test_native_nginx_assets_preserve_strict_security_headers() -> None:
    strict_headers = (
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header X-Frame-Options "DENY" always;',
        'add_header Referrer-Policy "same-origin" always;',
        'add_header Permissions-Policy "camera=(), geolocation=(), microphone=()" always;',
        'add_header Strict-Transport-Security "max-age=31536000" always;',
        "add_header Content-Security-Policy \"default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'\" always;",
    )

    for path in NATIVE_NGINX_SECURITY_PATHS:
        configuration = path.read_text(encoding="utf-8")
        assets_location = _prefix_location(configuration, "/assets/")

        assert 'add_header Cache-Control "public, immutable";' in assets_location
        for header in strict_headers:
            assert header in assets_location
        assert "'unsafe-eval'" not in assets_location
        assert "worker-src" not in assets_location
        assert 'X-Frame-Options "SAMEORIGIN"' not in assets_location


def test_internal_assets_preserve_strict_security_headers() -> None:
    strict_headers = (
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header X-Frame-Options "DENY" always;',
        'add_header Referrer-Policy "same-origin" always;',
        'add_header Permissions-Policy "camera=(), geolocation=(), microphone=()" always;',
        'add_header Strict-Transport-Security "max-age=31536000" always;',
        "add_header Content-Security-Policy \"default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'\" always;",
    )

    for path in NGINX_SECURITY_PATHS:
        configuration = path.read_text(encoding="utf-8")
        internal_assets = _prefix_location(
            configuration,
            "/_leadtrace_internal_assets/",
        )

        for header in strict_headers:
            assert header in internal_assets
        assert "'unsafe-eval'" not in internal_assets
        assert "worker-src" not in internal_assets
        assert 'X-Frame-Options "SAMEORIGIN"' not in internal_assets


def test_cutover_runbook_runs_isolated_caddy_header_preflight() -> None:
    runbook = CUTOVER_RUNBOOK_PATH.read_text(encoding="utf-8")
    section_start = runbook.index("## Scope Ketcher security headers")
    section_end = runbook.index("## Provision an isolated candidate", section_start)
    caddy_section = runbook[section_start:section_end]

    assert "-X-Powered-By" in caddy_section
    assert "-Server" in caddy_section
    assert "127.0.0.1:18878" in caddy_section
    assert "127.0.0.1:20199" in caddy_section
    assert "caddy run" in caddy_section
    assert "caddy stop" in caddy_section
    assert "skip_install_trust" in caddy_section
    assert 'find "$LEADTRACE_FRONTEND_RELEASE/assets"' in caddy_section
    assert 'curl -kfsSI "$candidate_origin$asset_url"' in caddy_section
    assert "https://127.0.0.1:8877" not in caddy_section
    assert "/etc/caddy/Caddyfile" not in caddy_section


def test_frontend_csp_e2e_script_builds_current_dist_without_vite_server() -> None:
    package = json.loads(FRONTEND_PACKAGE_PATH.read_text(encoding="utf-8"))
    runbook = CUTOVER_RUNBOOK_PATH.read_text(encoding="utf-8")

    assert package["scripts"]["test:ketcher-csp"] == (
        "npm run build && playwright test --config=e2e "
        "ketcher-csp.spec.ts --browser=chromium"
    )
    assert "npm run test:ketcher-csp" in runbook


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
