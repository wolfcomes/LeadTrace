from __future__ import annotations

from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from pathlib import Path

from app.database import create_database_engine
from app.papers.repository import PaperListFilters, published_paper_statement


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

    for required in (
        "LEADTRACE_LOAD_REGION_ID",
        "LEADTRACE_LOAD_RELEASE_ID",
        "/crop-jobs",
        "/validation",
        "PDF first visible content",
        "cached PDF page",
        "crop job enqueue",
        "release validation",
    ):
        assert required in profile
