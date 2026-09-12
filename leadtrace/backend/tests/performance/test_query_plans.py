from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from rdkit import Chem
from sqlalchemy import text

from app.database import create_database_engine
from app.papers.repository import PaperListFilters, published_paper_statement
from leadtrace.tests.load.scenario_data import (
    COLD_PREVIEW_MIN_SAMPLES,
    cold_preview_payload,
)


def _alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    return config


def _node_types(node: dict[str, object]) -> set[str]:
    types = {str(node.get("Node Type", ""))}
    for child in node.get("Plans", []):
        types.update(_node_types(child))
    return types


def test_current_release_lookup_has_an_index_plan(
    empty_postgresql_database_url: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET enable_seqscan = off"))
            plan = connection.execute(
                text(
                    "EXPLAIN (FORMAT JSON) "
                    "SELECT id FROM releases WHERE is_current LIMIT 1"
                )
            ).scalar_one()[0]["Plan"]
    finally:
        engine.dispose()

    assert _node_types(plan) & {"Index Scan", "Index Only Scan", "Bitmap Index Scan"}


def test_published_paper_list_statement_is_release_scoped_and_bounded() -> None:
    statement = published_paper_statement(
        uuid4(),
        PaperListFilters(search="kinase", sort="manifest"),
        page=2,
        page_size=20,
    )
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert "release_items.release_id" in compiled
    assert "LIMIT 20" in compiled
    assert "OFFSET 20" in compiled
    assert "ORDER BY release_items.manifest_order" in compiled


def test_load_profile_covers_queues_release_validation_and_pdf_latency() -> None:
    profile = (
        Path(__file__).parents[3] / "tests" / "load" / "locustfile.py"
    ).read_text(encoding="utf-8")
    readme = (
        Path(__file__).parents[3] / "tests" / "load" / "README.md"
    ).read_text(encoding="utf-8")

    for required in (
        "LEADTRACE_LOAD_REGION_ID",
        "LEADTRACE_LOAD_RELEASE_ID",
        "/crop-jobs",
        "/validation",
        "PDF first visible content",
        "cached PDF page",
        "crop job enqueue",
        "release validation",
        "/structures/drawings",
        "cold structure preview",
        '("POST", "cold structure preview"): 2000',
        "MIN_REQUEST_SAMPLES",
        "drawing_was_reused",
    ):
        assert required in profile
    assert "synchronous" in readme
    assert "automated hard gate" in readme
    assert "crop jobs are queued" in readme
    assert "unique" in readme
    assert "non-reused" in readme


def test_load_profile_generates_distinct_parseable_cold_preview_requests() -> None:
    payloads = [cold_preview_payload(token) for token in range(1, 101)]
    drawing_keys = {
        (payload["smiles"], payload["width"], payload["height"])
        for payload in payloads
    }

    assert len(drawing_keys) == len(payloads)
    assert all(Chem.MolFromSmiles(payload["smiles"]) is not None for payload in payloads)
    assert COLD_PREVIEW_MIN_SAMPLES >= 25
