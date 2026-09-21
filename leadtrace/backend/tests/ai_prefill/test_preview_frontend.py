from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings


def test_preview_serves_spa_routes_assets_and_nonsecret_identity(tmp_path):
    from app.ai_prefill.preview_server import install_preview_frontend

    (tmp_path / "index.html").write_text('<html><div id="app">Preview</div></html>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text('console.log("Preview")')
    instance = uuid4()
    settings = Settings(_env_file=None, environment="preview", preview_instance_id=instance,
                        preview_baseline_sha256="a" * 64, session_secret="secret-value")
    app = FastAPI()
    install_preview_frontend(app, settings, frontend_root=tmp_path)
    with TestClient(app) as client:
        for path in ("/", "/login", "/review/tasks", "/review/papers/123", "/admin/papers"):
            response = client.get(path)
            assert response.status_code == 200
            assert '<div id="app">' in response.text
            assert response.headers["cache-control"] == "no-store"
        assert client.get("/assets/app.js").status_code == 200
        identity = client.get("/api/preview/environment")
        assert identity.json() == {"environment": "preview", "instance_id": str(instance),
                                   "baseline_sha256": "a" * 64, "frontend_available": True}
        assert "secret" not in identity.text
        for path in ("/api/missing", "/health/missing", "/assets/missing.js", "/runtime.json", "/unregistered"):
            response = client.get(path)
            assert response.status_code == 404
            assert '<div id="app">' not in response.text


def test_preview_frontend_missing_build_reports_api_only(tmp_path):
    from app.ai_prefill.preview_server import install_preview_frontend

    app = FastAPI()
    settings = Settings(_env_file=None, environment="preview", preview_instance_id=uuid4(),
                        preview_baseline_sha256="a" * 64)
    install_preview_frontend(app, settings, frontend_root=tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/preview/environment").json()["frontend_available"] is False
        assert client.get("/login").status_code == 404


def test_production_does_not_get_preview_routes(tmp_path):
    from app.ai_prefill.preview_server import install_preview_frontend

    (tmp_path / "index.html").write_text("Preview")
    app = FastAPI()
    install_preview_frontend(app, Settings(_env_file=None, environment="test"), frontend_root=tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/preview/environment").status_code == 404
        assert client.get("/").status_code == 404
