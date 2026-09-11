from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.releases.models import Release
from tests.api.conftest import PublishedApiFixture


def test_visitor_reads_only_the_revision_pinned_by_the_current_release(
    published_api: PublishedApiFixture,
) -> None:
    response = published_api.client.get(
        f"/api/v1/papers/{published_api.detail_paper_id}",
        params={
            "revision_id": str(published_api.draft_revision_id),
            "include_drafts": "true",
        },
        headers={"X-Request-ID": "visitor-request-001"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "visitor-request-001"
    payload = response.json()
    assert payload["request_id"] == "visitor-request-001"
    assert payload["release"]["id"] == str(published_api.release_id)
    assert payload["paper"]["revision_id"] == str(
        published_api.published_revision_id
    )
    assert payload["paper"]["title"] == "Published optimization study 24"
    assert "SECRET newer draft title" not in response.text
    assert "/private/source" not in response.text
    assert "source_pdf" not in response.text


def test_paper_detail_contains_only_release_pinned_scientific_objects(
    published_api: PublishedApiFixture,
) -> None:
    response = published_api.client.get(
        f"/api/v1/papers/{published_api.detail_paper_id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["label"] for item in payload["compounds"]] == ["26a′", "26b"]
    assert payload["lineages"][0]["lineage_key"] == "LINEAGE-1"
    assert payload["lineage_edges"][0]["relation_status"] == "text_explicit"
    assert payload["structures"][0] == {
        "id": payload["structures"][0]["id"],
        "revision_id": payload["structures"][0]["revision_id"],
        "compound_id": payload["structures"][0]["compound_id"],
        "state": "structure_confirmed",
        "canonical_smiles": "CCN",
    }
    assert payload["evidence"][0]["text"] == "Potency improved."
    assert payload["activities"][0]["metric"] == "IC50"
    assert payload["activities"][0]["value"] == "12"
    assert payload["activities"][0]["unit"] == "nM"
    assert payload["quality_summary"] == {
        "relations": {"resolved": 1, "total": 1},
            "structures": {"confirmed": 2, "total": 2},
        "pair_ready": {"eligible": 1, "total": 1},
            "human_review": {"reviewed": 0, "total": 9},
    }


def test_unpublished_and_unknown_paper_ids_have_the_same_safe_error(
    published_api: PublishedApiFixture,
) -> None:
    hidden = published_api.client.get(
        f"/api/v1/papers/{published_api.unpublished_paper_id}"
    )
    missing = published_api.client.get(f"/api/v1/papers/{uuid4()}")

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["code"] == missing.json()["code"] == "RESOURCE_NOT_FOUND"
    assert hidden.json()["message"] == missing.json()["message"]
    assert hidden.json()["details"] == missing.json()["details"] == {}
    assert hidden.json()["request_id"]
    assert hidden.headers["X-Request-ID"] == hidden.json()["request_id"]
    assert "/private/" not in hidden.text
    assert "Traceback" not in hidden.text


def test_paper_list_defaults_to_twenty_items_in_manifest_order(
    published_api: PublishedApiFixture,
) -> None:
    first = published_api.client.get("/api/v1/papers")
    second = published_api.client.get("/api/v1/papers", params={"page": 2})

    assert first.status_code == second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["release"]["id"] == str(published_api.release_id)
    assert first_payload["pagination"] == {
        "page": 1,
        "page_size": 20,
        "total_items": 25,
        "total_pages": 2,
    }
    assert [item["paper_key"] for item in first_payload["items"]] == list(
        published_api.ordered_paper_keys[:20]
    )
    assert [item["paper_key"] for item in second_payload["items"]] == list(
        published_api.ordered_paper_keys[20:]
    )
    assert second_payload["pagination"]["page_size"] == 20


def test_paper_filters_are_url_compatible_and_release_scoped(
    published_api: PublishedApiFixture,
) -> None:
    cases = [
        ({"search": "study 07"}, "paper-07"),
        ({"doi": "10.1000/paper-07"}, "paper-07"),
        ({"target": "Kinase A", "sort": "paper_id"}, "paper-00"),
        ({"has_lineage": "true"}, "paper-24"),
        ({"relation_status": "text_explicit"}, "paper-24"),
        ({"structure_state": "structure_confirmed"}, "paper-24"),
        ({"review_status": "unreviewed", "sort": "-paper_id"}, "paper-24"),
    ]

    for params, expected_first_key in cases:
        response = published_api.client.get("/api/v1/papers", params=params)
        assert response.status_code == 200
        assert response.json()["items"][0]["paper_key"] == expected_first_key
        assert response.json()["filters"] == {
            "search": params.get("search"),
            "doi": params.get("doi"),
            "target": params.get("target"),
            "has_lineage": params.get("has_lineage"),
            "relation_status": params.get("relation_status"),
            "structure_state": params.get("structure_state"),
            "review_status": params.get("review_status"),
            "sort": params.get("sort", "manifest"),
        }


def test_no_current_release_is_reported_without_falling_back_to_drafts(
    published_api: PublishedApiFixture,
) -> None:
    with published_api.session_factory.begin() as session:
        release = session.scalar(
            select(Release).where(Release.id == published_api.release_id)
        )
        assert release is not None
        release.is_current = False

    response = published_api.client.get("/api/v1/papers")

    assert response.status_code == 404
    assert response.json()["code"] == "CURRENT_RELEASE_NOT_FOUND"
    assert response.json()["details"] == {}
