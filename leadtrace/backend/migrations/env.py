from __future__ import annotations

from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.activities import models as activity_models  # noqa: F401
from app.assets import models as asset_models  # noqa: F401
from app.auth import models as auth_models  # noqa: F401
from app.compounds import models as compound_models  # noqa: F401
from app.database import postgresql_url
from app.db.base import Base
from app.evidence import models as evidence_models  # noqa: F401
from app.lineages import models as lineage_models  # noqa: F401
from app.papers import models as paper_models  # noqa: F401
from app.revisions import models as revision_models  # noqa: F401
from app.structures import models as structure_models  # noqa: F401
from app.users import models as user_models  # noqa: F401
from app.visual_objects import models as visual_object_models  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

explicit_database_url = config.attributes.get("leadtrace_database_url")
runtime_database_url = (
    str(explicit_database_url).strip()
    if explicit_database_url is not None
    else os.environ.get("LEADTRACE_DATABASE_URL", "").strip()
)
if runtime_database_url:
    normalized_database_url = postgresql_url(runtime_database_url).render_as_string(
        hide_password=False
    )
    config.set_main_option(
        "sqlalchemy.url",
        normalized_database_url.replace("%", "%%"),
    )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        expected_database_name = config.attributes.get(
            "leadtrace_expected_database_name"
        )
        if expected_database_name is not None:
            actual_database_name = connection.connection.driver_connection.info.dbname
            if actual_database_name != expected_database_name:
                raise RuntimeError(
                    "Alembic connected to an unexpected database: "
                    f"expected database {expected_database_name!r}, "
                    f"got {actual_database_name!r}"
                )
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
