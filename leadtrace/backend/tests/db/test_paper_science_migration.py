from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from app.database import create_database_engine


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"

SCIENCE_TABLES = {
    "compounds",
    "structures",
    "structure_source_images",
    "lineages",
    "lineage_members",
    "lineage_edges",
    "evidence",
    "edge_evidence_links",
    "activities",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        database_url
    ).database
    return config


def test_paper_science_migration_installs_tables_and_query_indexes(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)

    command.upgrade(config, "head")

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names(schema="public"))
        assert SCIENCE_TABLES <= tables
        structure_columns = {
            column["name"] for column in inspector.get_columns("structures")
        }
        indexes = {
            index["name"]
            for table in SCIENCE_TABLES
            for index in inspector.get_indexes(table, schema="public")
        }
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

    assert ScriptDirectory.from_config(config).get_current_head() == (
        "0022_crop_job_source_provenance"
    )
    assert revision == "0022_crop_job_source_provenance"
    assert "structure_proposals" not in tables
    assert "confidence" not in structure_columns
    assert "confidence_score" not in structure_columns
    assert {
        "ix_compounds_workspace_order",
        "ix_lineages_workspace_order",
        "ix_lineage_edges_endpoints",
        "ix_evidence_workspace_page",
        "ix_activities_compound_order",
    } <= indexes
