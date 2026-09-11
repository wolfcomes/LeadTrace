from __future__ import annotations

import pytest

from tests.documents.conftest import DocumentFixture, login


@pytest.mark.parametrize(
    ("range_value", "start", "end"),
    [
        ("bytes=0-8", 0, 8),
        ("bytes=9-", 9, None),
        ("bytes=-6", -6, None),
    ],
)
def test_single_byte_ranges_return_206_and_correct_content_range(
    document_fixture: DocumentFixture,
    range_value: str,
    start: int,
    end: int | None,
) -> None:
    login(document_fixture.client, "document.reviewer")

    response = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        headers={"Range": range_value},
    )

    assert response.status_code == 206
    expected_start = start if start >= 0 else len(document_fixture.article_payload) + start
    expected_end = end if end is not None else len(document_fixture.article_payload) - 1
    expected_body = document_fixture.article_payload[expected_start:expected_end + 1]
    assert response.content == expected_body
    assert response.headers["Content-Range"] == (
        f"bytes {expected_start}-{expected_end}/{len(document_fixture.article_payload)}"
    )
    assert response.headers["Content-Length"] == str(len(expected_body))
    assert response.headers["Accept-Ranges"] == "bytes"


@pytest.mark.parametrize(
    "range_value",
    ["bytes=999-1000", "bytes=9-2", "bytes=0-1,3-4", "items=0-1", "bytes=-0"],
)
def test_invalid_or_unsatisfiable_ranges_return_416_without_file_data(
    document_fixture: DocumentFixture,
    range_value: str,
) -> None:
    login(document_fixture.client, "document.reviewer")

    response = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        headers={"Range": range_value},
    )

    assert response.status_code == 416
    assert response.content == b""
    assert response.headers["Content-Range"] == (
        f"bytes */{len(document_fixture.article_payload)}"
    )
    assert "/tmp/" not in response.text


def test_full_response_is_used_when_range_header_is_absent(
    document_fixture: DocumentFixture,
) -> None:
    login(document_fixture.client, "document.reviewer")

    response = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf"
    )

    assert response.status_code == 200
    assert response.content == document_fixture.article_payload
    assert "Content-Range" not in response.headers
