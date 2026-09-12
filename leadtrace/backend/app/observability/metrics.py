from __future__ import annotations

import secrets
from collections import Counter
from threading import Lock

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import SecretStr


class MetricsRegistry:
    """Process-local, low-cardinality HTTP metrics for a single web worker."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: Counter[tuple[str, str, str]] = Counter()
        self._duration_seconds: Counter[tuple[str, str]] = Counter()

    def observe(self, *, method: str, route: str, status_code: int, duration_seconds: float) -> None:
        status_class = f"{status_code // 100}xx"
        with self._lock:
            self._requests[(method, route, status_class)] += 1
            self._duration_seconds[(method, route)] += max(duration_seconds, 0.0)

    def render(self) -> str:
        lines = [
            "# HELP leadtrace_http_requests_total Total HTTP requests.",
            "# TYPE leadtrace_http_requests_total counter",
        ]
        with self._lock:
            request_rows = sorted(self._requests.items())
            duration_rows = sorted(self._duration_seconds.items())
        for (method, route, status_class), value in request_rows:
            labels = _labels(method=method, route=route, status_class=status_class)
            lines.append(f"leadtrace_http_requests_total{{{labels}}} {value}")
        lines.extend(
            [
                "# HELP leadtrace_http_request_duration_seconds_sum Total HTTP request time.",
                "# TYPE leadtrace_http_request_duration_seconds_sum counter",
            ]
        )
        for (method, route), value in duration_rows:
            labels = _labels(method=method, route=route)
            lines.append(f"leadtrace_http_request_duration_seconds_sum{{{labels}}} {value:.6f}")
        return "\n".join(lines) + "\n"


def _labels(**values: str) -> str:
    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    return ",".join(f'{key}="{escape(value)}"' for key, value in sorted(values.items()))


def create_metrics_router(
    registry: MetricsRegistry,
    bearer_token: SecretStr | None,
) -> APIRouter:
    router = APIRouter(tags=["internal metrics"])

    @router.get("/internal/metrics", include_in_schema=False)
    def metrics(authorization: str | None = Header(default=None)) -> PlainTextResponse:
        expected = bearer_token.get_secret_value() if bearer_token is not None else ""
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ").strip()
        if not expected or not supplied or not secrets.compare_digest(supplied, expected):
            raise HTTPException(status_code=404, detail="Resource not found")
        return PlainTextResponse(
            registry.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return router
