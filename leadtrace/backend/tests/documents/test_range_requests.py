from __future__ import annotations

import pytest


def _login(client, username: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Document test password 2026!"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(("range_value", "start", "end"), [("bytes=0-8", 0, 8), ("bytes=9-", 9, None), ("bytes=-6", -6, None)])
def test_v2_source_pdf_supports_one_byte_range(document_fixture, range_value: str, start: int, end: int | None) -> None:
    _login(document_fixture.client, "document.reviewer")
    response = document_fixture.client.get(f"/api/v2/papers/{document_fixture.paper_id}/source-pdf", headers={"Range": range_value})
    expected_start = start if start >= 0 else len(document_fixture.payload) + start
    expected_end = end if end is not None else len(document_fixture.payload) - 1
    assert response.status_code == 206
    assert response.content == document_fixture.payload[expected_start : expected_end + 1]
    assert response.headers["Content-Range"] == f"bytes {expected_start}-{expected_end}/{len(document_fixture.payload)}"
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("range_value", ["bytes=999999-1000000", "bytes=9-2", "bytes=0-1,3-4", "items=0-1", "bytes=-0"])
def test_v2_source_pdf_rejects_invalid_or_multiple_ranges(document_fixture, range_value: str) -> None:
    _login(document_fixture.client, "document.reviewer")
    response = document_fixture.client.get(f"/api/v2/papers/{document_fixture.paper_id}/source-pdf", headers={"Range": range_value})
    assert response.status_code == 416
    assert response.content == b""
    assert response.headers["Content-Range"] == f"bytes */{len(document_fixture.payload)}"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert str(document_fixture.source_path) not in response.text
