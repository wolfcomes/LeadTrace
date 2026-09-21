"""Preview acceptance uses fresh _preview databases, never the reset fixture."""
from collections.abc import Iterator
import json
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.ai_prefill.preview_models import PreviewMarker
from .test_apply import create_ai_context


@pytest.fixture
def preview_database_url(postgresql_database_url: str) -> Iterator[str]:
    # The explicit test target is the provisioning connection only. It is never
    # renamed or reset here. Each test owns the DB it successfully creates.
    parent = make_url(postgresql_database_url)
    with psycopg.connect(postgresql_database_url.replace("postgresql+psycopg://", "postgresql://", 1), autocommit=True) as admin:
        assert admin.info.dbname == parent.database
        assert admin.info.dbname.endswith("_test")
        name = f"leadtrace_{uuid4().hex}_preview"
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        try:
            url = parent.set(database=name).render_as_string(hide_password=False)
            config = Config("alembic.ini")
            config.attributes["leadtrace_database_url"] = url
            config.attributes["leadtrace_expected_database_name"] = name
            command.upgrade(config, "head")
            yield url
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def preview_session_factory(preview_database_url):
    engine = create_database_engine(preview_database_url)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture
def preview_ai_context(preview_session_factory, preview_settings):
    import hashlib
    from app.assets.models import Asset
    from app.catalog.models import PaperSource
    from app.papers.models import Paper
    from .test_preview_application import preview_pdf_bytes
    context = create_ai_context(preview_session_factory)
    content = preview_pdf_bytes()
    path = preview_settings.source_roots["source_pdfs"] / "volume67 issue5/ai-paper.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with preview_session_factory.begin() as session:
        paper = session.get(Paper, context.paper_id)
        source = session.get(PaperSource, paper.source_id)
        asset = session.get(Asset, source.asset_id)
        source.sha256 = asset.sha256 = hashlib.sha256(content).hexdigest()
        source.byte_size = asset.byte_size = len(content)
    return context


@pytest.fixture
def preview_settings(preview_session_factory, preview_database_url, tmp_path: Path):
    instance_id = uuid4()
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    with preview_session_factory.begin() as session:
        session.add(PreviewMarker(instance_id=instance_id, baseline_sha256="b" * 64, schema_revision=head))
    url = make_url(preview_database_url)
    roots = {name: tmp_path / name for name in ("assets", "sources", "artifacts")}
    for path in roots.values():
        path.mkdir()
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({
        "schema_version": 1, "state": "ready", "instance_id": str(instance_id),
        "baseline_sha256": "b" * 64, "schema_revision": head,
        "database_name": url.database,
        "database_host": url.query.get("host", url.host),
        "database_port": int(url.query.get("port", url.port or 5432)),
        "asset_root": str(roots["assets"]), "source_root": str(roots["sources"]),
        "artifact_root": str(roots["artifacts"]),
        "commit": "test-fixture", "lockfile_sha256": "c" * 64,
    }))
    return Settings(
        _env_file=None, environment="preview", database_url=preview_database_url,
        session_secret="preview-http-test-secret-over-thirty-two-characters",
        allowed_hosts=["testserver"], asset_root=roots["assets"],
        source_roots={"source_pdfs": roots["sources"]},
        preview_artifact_root=roots["artifacts"], preview_registry_path=registry_path,
        preview_instance_id=instance_id, preview_baseline_sha256="b" * 64,
    )
