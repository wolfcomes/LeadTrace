from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.assets.storage import LocalAssetStore
from app.api.errors import APIError, request_id_for
from app.audit.service import AuditService, canonical_content_hash
from app.auth.router import resolve_remote_address
from app.database import get_db_session
from app.documents.service import (
    DocumentKind,
    DocumentNotFound,
    DocumentService,
    RangeNotSatisfiable,
    iter_file_range,
)
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
)
from app.security.policies import Principal


def _safe_filename(filename: str) -> str:
    candidate = filename.replace("\r", "").replace("\n", "").replace('"', "'")
    candidate = candidate.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return candidate or "source.pdf"


def _headers(asset, *, partial: bool, start: int, end: int, full_size: int) -> dict[str, str]:
    filename = _safe_filename(asset.original_filename)
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'inline; filename="{filename}"',
        "Content-Type": "application/pdf",
        "ETag": f'"{asset.sha256}"',
        "X-Content-Type-Options": "nosniff",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{full_size}"
    headers["Content-Length"] = str(end - start + 1)
    return headers


def _internal_transfer_path(storage_key: str) -> str | None:
    if not storage_key.startswith("managed/"):
        return None
    relative_key = storage_key.removeprefix("managed/")
    return f"/_leadtrace_internal_assets/{quote(relative_key, safe='/')}"


def create_documents_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/papers", tags=["protected documents"])
    service = DocumentService()
    audit_service = AuditService()

    @router.get("/{paper_id}/source-pdf")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def source_pdf(
        paper_id: UUID,
        request: Request,
        kind: DocumentKind = Query(default=DocumentKind.ARTICLE),
        range_header: str | None = Header(default=None, alias="Range"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> Response:
        settings = request.app.state.settings
        store = LocalAssetStore(
            settings.asset_root,
            source_roots=settings.source_roots,
        )
        try:
            with session.begin():
                document = service.resolve(
                    session,
                    paper_id=paper_id,
                    kind=kind,
                    principal=principal,
                    store=store,
                    range_header=range_header,
                )
                status_code = 206 if range_header is not None else 200
                audit_service.append_event(
                    session,
                    actor_id=principal.user_id,
                    action="document.pdf.viewed",
                    target_type="asset",
                    target_id=document.asset.id,
                    paper_id=document.paper.id,
                    changeset_id=None,
                    release_id=None,
                    ip_address=resolve_remote_address(request, settings),
                    request_id=request_id_for(request),
                    result="success",
                    reason="Viewed protected source PDF",
                    before_hash=canonical_content_hash(None),
                    after_hash=document.asset.sha256,
                    details={
                        "asset_id": str(document.asset.id),
                        "document_kind": kind.value,
                        "range": (
                            {
                                "start": document.byte_range.start,
                                "end": document.byte_range.end,
                            }
                            if status_code == 206
                            else None
                        ),
                        "bytes_served": document.byte_range.length,
                    },
                )
        except DocumentNotFound:
            raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found") from None
        except RangeNotSatisfiable as error:
            return Response(
                status_code=416,
                headers={
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "private, no-store",
                    "Content-Range": f"bytes */{error.size}",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        partial = status_code == 206
        headers = _headers(
            document.asset,
            partial=partial,
            start=document.byte_range.start,
            end=document.byte_range.end,
            full_size=document.full_size,
        )
        if partial:
            headers["Content-Range"] = (
                f"bytes {document.byte_range.start}-{document.byte_range.end}/"
                f"{document.full_size}"
            )
        transfer_path = (
            _internal_transfer_path(document.asset.storage_key)
            if settings.nginx_internal_transfer
            else None
        )
        if transfer_path is not None:
            headers["X-Accel-Redirect"] = transfer_path
            return Response(status_code=status_code, headers=headers)
        return StreamingResponse(
            iter_file_range(document.path, document.byte_range),
            status_code=status_code,
            headers=headers,
            media_type="application/pdf",
        )

    return router
