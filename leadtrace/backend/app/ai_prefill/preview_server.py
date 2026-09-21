"""Internal subprocess entrypoint: credentials are read from a protected file."""
from __future__ import annotations

import argparse
from pathlib import Path
import socket

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from app.ai_prefill.preview_process import load_runtime_settings
from app.config import Settings


class _PreviewFrontend(StaticFiles):
    """Serve browser history routes without hiding missing API or asset URLs."""

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            parts = Path(path).parts
            is_ui_route = path in {".", "", "login", "change-password"} or (
                parts and parts[0] in {"papers", "review", "admin"}
                and not any("." in part for part in parts)
            )
            if error.status_code != 404 or not is_ui_route:
                raise
            response = FileResponse(Path(self.directory) / "index.html")
        # A rebuilt Preview must not continue running a cached previous bundle.
        response.headers["Cache-Control"] = "no-store"
        return response


def install_preview_frontend(application: FastAPI, settings: Settings, *, frontend_root: Path | None = None) -> None:
    """Add a same-origin UI only to the native Preview application."""
    if settings.environment != "preview":
        return
    root = frontend_root if frontend_root is not None else Path(__file__).resolve().parents[3] / "frontend" / "dist"
    available = (root / "index.html").is_file()

    @application.get("/api/preview/environment", include_in_schema=False)
    def preview_environment():
        return {"environment": "preview", "instance_id": str(settings.preview_instance_id),
                "baseline_sha256": settings.preview_baseline_sha256, "frontend_available": available}

    if available:
        application.mount("/", _PreviewFrontend(directory=root), name="preview-frontend")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the native Preview backend")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--fd", required=True, type=int)
    args = parser.parse_args()
    settings = load_runtime_settings(args.profile)
    # app.main also constructs a module-level ASGI app. Bind its settings
    # factory first so that import cannot consult a neighboring .env file.
    import app.config
    app.config.get_settings = lambda: settings
    from app.main import create_app
    import uvicorn
    application = create_app(settings=settings)
    install_preview_frontend(application, settings)
    with socket.socket(fileno=args.fd) as listener:
        config = uvicorn.Config(application, log_config=None,
            access_log=False, log_level="critical", timeout_graceful_shutdown=8)
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    main()
