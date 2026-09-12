from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any

from fastapi import FastAPI, Request

from app.api.errors import request_id_for
from app.observability.metrics import MetricsRegistry


REQUEST_LOGGER = logging.getLogger("leadtrace.request")
SAFE_PATH_IDS = {
    "paper_id",
    "changeset_id",
    "release_id",
    "job_id",
}


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/"):
        return template
    return "<unmatched>"


def _safe_context(request: Request) -> dict[str, object]:
    context: dict[str, object] = {}
    actor_id = getattr(request.state, "actor_id", None)
    if actor_id is not None:
        context["actor_id"] = str(actor_id)
    for name in SAFE_PATH_IDS:
        value = request.path_params.get(name)
        if value is not None:
            context[name] = str(value)
    return context


def install_request_observability(
    application: FastAPI,
    registry: MetricsRegistry,
) -> None:
    REQUEST_LOGGER.disabled = False

    @application.middleware("http")
    async def observe_request(request: Request, call_next: Any) -> Any:
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_seconds = perf_counter() - started
            route = _route_template(request)
            registry.observe(
                method=request.method,
                route=route,
                status_code=status_code,
                duration_seconds=duration_seconds,
            )
            result = "success" if status_code < 400 else "failure"
            record: dict[str, object] = {
                "duration_ms": round(duration_seconds * 1000, 3),
                "event": "http_request",
                "method": request.method,
                "request_id": request_id_for(request),
                "result": result,
                "role": getattr(request.state, "actor_role", None),
                "route": route,
                "status_code": status_code,
            }
            record.update(_safe_context(request))
            if status_code >= 400:
                record["error_code"] = getattr(
                    request.state,
                    "error_code",
                    f"HTTP_{status_code}",
                )
            REQUEST_LOGGER.info(
                json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            )
