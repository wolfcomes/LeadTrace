from uuid import uuid4

from app.publications.schemas import PublishedActivityTable


def test_public_table_projection_omits_workspace_ownership_and_creator():
    identifier = str(uuid4())
    source = dict(id=identifier, name="Table 1", kind="source", source_label="Table 1",
        source_title="Potency", page_number=1, review_hint=None, columns=[],
        mode="any", sort="label", review_status="reviewer_confirmed",
        workspace_id=str(uuid4()), paper_id=str(uuid4()), created_by_kind="reviewer")
    result = PublishedActivityTable.model_validate(source).model_dump(mode="json")
    assert result == {k:v for k,v in source.items() if k not in {"workspace_id", "paper_id", "created_by_kind"}}
    assert source["workspace_id"]
