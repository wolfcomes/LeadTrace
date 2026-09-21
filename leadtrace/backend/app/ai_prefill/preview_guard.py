"""Recheck Preview identity before each request transaction, including auth."""
from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.ai_prefill.preview_identity import PreviewIdentityError, verify_preview_connection
from app.api.errors import APIError
from app.database import get_request_db_session


def enforce_preview_identity(
    request: Request,
    session: Session | None = Depends(get_request_db_session),
) -> Generator[None, None, None]:
    settings = request.app.state.settings
    if settings.environment != "preview":
        yield
        return
    if session is None:
        raise APIError(503, "PREVIEW_IDENTITY_MISMATCH", "Preview instance is unavailable")

    def check_transaction(_session: Session, transaction: object, connection: Connection) -> None:
        if getattr(transaction, "parent", None) is None:
            verify_preview_connection(settings, connection)

    event.listen(session, "after_begin", check_transaction)
    try:
        # Check even routes which would otherwise perform only filesystem work.
        with session.begin():
            session.connection()
        yield
    except PreviewIdentityError as error:
        raise APIError(503, "PREVIEW_IDENTITY_MISMATCH", "Preview instance identity could not be verified") from error
    finally:
        event.remove(session, "after_begin", check_transaction)
