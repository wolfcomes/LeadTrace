from __future__ import annotations

import argparse

from sqlalchemy.orm import Session, sessionmaker

from app.audit.service import AuditService
from app.config import get_settings
from app.database import bootstrap_database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.audit",
        description="Verify the append-only LeadTrace audit hash chain.",
    )
    parser.add_subparsers(dest="command", required=True).add_parser(
        "verify", help="Verify sequence, links, payload hashes, and chain head"
    )
    return parser


def verify(
    _: argparse.Namespace,
    *,
    session_factory: sessionmaker[Session],
) -> int:
    with session_factory() as session:
        with session.begin():
            result = AuditService().verify_chain(session)
    first_invalid = (
        str(result.first_invalid_sequence)
        if result.first_invalid_sequence is not None
        else "none"
    )
    print(
        f"valid={str(result.valid).lower()} events={result.event_count} "
        f"first_invalid_sequence={first_invalid}"
    )
    return 0 if result.valid else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    resources = bootstrap_database(get_settings())
    try:
        if args.command == "verify":
            return verify(args, session_factory=resources.session_factory)
        raise AssertionError("Unsupported audit command")
    finally:
        resources.close()


if __name__ == "__main__":
    raise SystemExit(main())
