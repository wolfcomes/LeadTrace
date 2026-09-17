from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from sqlalchemy import delete

from app.compounds.models import Compound
from app.workspaces.models import PaperSection
from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash


def test_snapshot_is_canonical_and_contains_only_safe_source_keys(workspace_fixture):
    fixture = workspace_fixture
    with fixture.session_factory.begin() as session:
        first = build_paper_snapshot(session, fixture.workspace_id)
        second = build_paper_snapshot(session, fixture.workspace_id)

    assert first == second
    assert canonical_snapshot_hash(first) == canonical_snapshot_hash(second)
    assert first["source"] == {
        "asset_id": str(fixture.asset_id),
        "source_root_key": "source_pdfs",
        "source_key": "volume67 issue5/paper-01.pdf",
        "sha256": "a" * 64,
        "page_count": 12,
    }
    serialized = str(first)
    assert {item["section_key"] for item in first["sections"]} == {
        section.value for section in PaperSection
    }
    assert "/srv/private" not in serialized
    assert "must-never-be-returned" not in serialized
    assert "Second extracted title" not in serialized
    assert "password" not in serialized.casefold()


def test_snapshot_hash_does_not_depend_on_mapping_insertion_order(workspace_fixture):
    fixture = workspace_fixture
    with fixture.session_factory.begin() as session:
        snapshot = build_paper_snapshot(session, fixture.workspace_id)

    reordered = {
        key: snapshot[key]
        for key in reversed(list(snapshot))
    }
    reordered["paper"] = {
        key: snapshot["paper"][key]
        for key in reversed(list(snapshot["paper"]))
    }
    assert canonical_snapshot_hash(snapshot) == canonical_snapshot_hash(reordered)


def test_snapshot_is_not_mutated_by_hashing(workspace_fixture):
    fixture = workspace_fixture
    with fixture.session_factory.begin() as session:
        snapshot = build_paper_snapshot(session, fixture.workspace_id)
    original = deepcopy(snapshot)
    canonical_snapshot_hash(snapshot)
    assert snapshot == original


def test_snapshot_rows_are_stable_across_database_insertion_order(workspace_fixture):
    fixture = workspace_fixture
    compound_ids = (
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
    )

    def compound(compound_id: UUID, label: str, order: int) -> Compound:
        return Compound(
            id=compound_id,
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label=label,
            sort_order=order,
            created_by_kind="reviewer",
        )

    with fixture.session_factory.begin() as session:
        session.add_all(
            [compound(compound_ids[1], "B", 1), compound(compound_ids[0], "A", 0)]
        )
        session.flush()
        reverse_insert = build_paper_snapshot(session, fixture.workspace_id)

    with fixture.session_factory.begin() as session:
        session.execute(
            delete(Compound).where(Compound.workspace_id == fixture.workspace_id)
        )

    with fixture.session_factory.begin() as session:
        session.add_all(
            [compound(compound_ids[0], "A", 0), compound(compound_ids[1], "B", 1)]
        )
        session.flush()
        forward_insert = build_paper_snapshot(session, fixture.workspace_id)

    assert forward_insert == reverse_insert
    assert canonical_snapshot_hash(forward_insert) == canonical_snapshot_hash(
        reverse_insert
    )
