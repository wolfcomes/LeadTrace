from __future__ import annotations

from tests.api.conftest import PublishedApiFixture


def test_overview_reports_separate_metrics_with_explicit_denominators(
    published_api: PublishedApiFixture,
) -> None:
    response = published_api.client.get("/api/v1/published/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["release"]["id"] == str(published_api.release_id)
    assert payload["release"]["key"] == published_api.release_key
    assert payload["metrics"] == {
        "corpus": {"numerator": 672, "denominator": 672, "unit": "papers"},
        "lineage": {"numerator": 138, "denominator": 672, "unit": "papers"},
        "relation": {"numerator": 4144, "denominator": 4144, "unit": "edges"},
        "structure": {
            "numerator": 4011,
            "denominator": 4301,
            "unit": "compounds",
        },
        "pair": {"numerator": 1730, "denominator": 4144, "unit": "edges"},
        "human_review": {
            "numerator": 0,
            "denominator": 672,
            "unit": "papers",
        },
    }
    assert "completion" not in response.text.casefold()
    assert "16" not in response.text


def test_anonymous_caller_cannot_read_published_overview(
    published_api: PublishedApiFixture,
) -> None:
    published_api.client.cookies.clear()

    response = published_api.client.get("/api/v1/published/overview")

    assert response.status_code == 401
    assert response.json() == {
        "code": "AUTHENTICATION_REQUIRED",
        "message": "Authentication required",
        "details": {},
        "request_id": response.headers["X-Request-ID"],
    }
