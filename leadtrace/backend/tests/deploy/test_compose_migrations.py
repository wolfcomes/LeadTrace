from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_PATH = REPOSITORY_ROOT / "leadtrace" / "deploy" / "compose.yaml"
NGINX_PATH = REPOSITORY_ROOT / "leadtrace" / "deploy" / "nginx" / "nginx.conf"
DOCKERFILE_PATH = REPOSITORY_ROOT / "leadtrace" / "backend" / "Dockerfile"


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


def test_nginx_replaces_untrusted_forwarded_for_header() -> None:
    nginx_configuration = NGINX_PATH.read_text(encoding="utf-8")

    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx_configuration
    assert "$proxy_add_x_forwarded_for" not in nginx_configuration
    assert "proxy_set_header X-Real-IP $remote_addr;" in nginx_configuration


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
