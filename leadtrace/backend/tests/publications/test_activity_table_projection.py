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


def test_ai_row_order_cannot_overwrite_overlapping_reviewer_scope():
    import pytest
    from app.publications.comparison import _IncompleteHistory
    from app.publications.reviewer_projection import _apply_delta
    with pytest.raises(_IncompleteHistory, match='overlap'):
        _apply_delta({'compound_ids': ['human']}, {'compound_ids': None}, {'compound_ids': ['ai']}, table_columns=True)


def test_ai_row_evidence_delta_retains_unrelated_human_table_fields():
    from app.publications.reviewer_projection import _apply_delta
    target = {'name': 'Original', 'compound_ids': None, 'evidence_ids': []}
    before = {'name': 'Human title', 'compound_ids': None, 'evidence_ids': []}
    after = {'name': 'Human title', 'compound_ids': ['b', 'a'], 'evidence_ids': ['e2', 'e1']}
    _apply_delta(target, before, after, table_columns=True)
    assert target == {'name': 'Original', 'compound_ids': ['b', 'a'], 'evidence_ids': ['e2', 'e1']}
