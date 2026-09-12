from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from urllib.parse import unquote, urlparse


class RestoreTargetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    host: str
    port: int
    database: str


def _database_identity(database_url: str) -> DatabaseIdentity:
    parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    database = unquote(parsed.path.removeprefix("/"))
    try:
        port = parsed.port or 5432
    except ValueError as error:
        raise RestoreTargetError("restore database URL has an invalid port") from error
    if parsed.scheme != "postgresql" or not parsed.hostname or not database:
        raise RestoreTargetError("restore database URL must identify PostgreSQL")
    return DatabaseIdentity(parsed.hostname.casefold(), port, database)


def validate_restore_target(
    target_url: str,
    production_url: str,
    allowlisted_names: set[str],
) -> DatabaseIdentity:
    target = _database_identity(target_url)
    production = _database_identity(production_url)
    if target == production:
        raise RestoreTargetError("restore target is the production database")
    if target.database not in allowlisted_names:
        raise RestoreTargetError("restore target database is not explicitly allowlisted")

    import psycopg

    connection_url = target_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(connection_url, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            actual_database = str(cursor.fetchone()[0])
            if actual_database != target.database:
                raise RestoreTargetError("restore connection resolved to another database")
            cursor.execute(
                """
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname <> 'information_schema'
                  AND namespace.nspname NOT LIKE 'pg_%'
                  AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
                """
            )
            relation_count = int(cursor.fetchone()[0])
    if relation_count:
        raise RestoreTargetError("restore target database is not empty")
    return target


def main() -> int:
    target_url = os.environ.get("LEADTRACE_RESTORE_DATABASE_URL", "").strip()
    production_url = os.environ.get("LEADTRACE_PRODUCTION_DATABASE_URL", "").strip()
    allowlist = {
        value.strip()
        for value in os.environ.get(
            "LEADTRACE_RESTORE_DATABASE_ALLOWLIST", ""
        ).split(",")
        if value.strip()
    }
    if not target_url or not production_url or not allowlist:
        print(
            "leadtrace restore target: production identity and drill allowlist are required",
            file=sys.stderr,
        )
        return 2
    try:
        validate_restore_target(target_url, production_url, allowlist)
    except RestoreTargetError as error:
        print(f"leadtrace restore target: {error}", file=sys.stderr)
        return 2
    except Exception:
        print(
            "leadtrace restore target: database identity or emptiness check failed",
            file=sys.stderr,
        )
        return 2
    print("restore_target=allowlisted_empty_database")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
