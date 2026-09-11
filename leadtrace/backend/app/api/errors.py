from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class APIError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.safe_details = details or {}


def request_id_for(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str):
        return request_id
    request_id = uuid4().hex
    request.state.request_id = request_id
    return request_id


def _error_code(status_code: int, message: str) -> str:
    known_messages = {
        "Authentication required": "AUTHENTICATION_REQUIRED",
        "Invalid username or password": "AUTHENTICATION_REQUIRED",
        "Password change required": "PASSWORD_CHANGE_REQUIRED",
        "Recent reauthentication required": "RECENT_REAUTHENTICATION_REQUIRED",
        "CSRF validation failed": "CSRF_VALIDATION_FAILED",
        "Permission denied": "PERMISSION_DENIED",
        "Resource not found": "RESOURCE_NOT_FOUND",
    }
    if message in known_messages:
        return known_messages[message]
    return {
        400: "INVALID_REQUEST",
        401: "AUTHENTICATION_REQUIRED",
        403: "PERMISSION_DENIED",
        404: "RESOURCE_NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "REQUEST_FAILED")


def _safe_message(status_code: int, detail: Any) -> str:
    if status_code == 404:
        return "Resource not found"
    if isinstance(detail, str) and detail:
        return detail
    return "The request could not be completed"


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    request_id = request_id_for(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


def install_api_error_handling(application: FastAPI) -> None:
    @application.middleware("http")
    async def attach_request_id(request: Request, call_next: Any) -> Any:
        incoming = request.headers.get("X-Request-ID", "").strip()
        request.state.request_id = (
            incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else uuid4().hex
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(APIError)
    async def handle_api_error(request: Request, error: APIError) -> JSONResponse:
        return _error_response(
            request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=error.safe_details,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        _: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        message = _safe_message(error.status_code, error.detail)
        return _error_response(
            request,
            status_code=error.status_code,
            code=_error_code(error.status_code, message),
            message=message,
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _: Exception) -> JSONResponse:
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="The request could not be completed",
        )
