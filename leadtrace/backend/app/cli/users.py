from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import stat
from uuid import UUID

from app.config import get_settings
from app.database import bootstrap_database, transactional_session
from app.users.models import UserRole
from app.users.service import UserService


class SecretFileError(ValueError):
    pass


def read_password_file(path: Path) -> str:
    file_status = path.lstat()
    if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(file_status.st_mode):
        raise SecretFileError("Password file must be a regular, non-symlink file")
    if file_status.st_uid != os.getuid():
        raise SecretFileError("Password file must be owned by the current user")
    if stat.S_IMODE(file_status.st_mode) & 0o077:
        raise SecretFileError("Password file permissions must be owner-only (0600)")
    if file_status.st_size > 16_384:
        raise SecretFileError("Password file is unexpectedly large")
    password = path.read_text(encoding="utf-8").rstrip("\r\n")
    if not password:
        raise SecretFileError("Password file is empty")
    return password


def _read_password(password_file: Path | None) -> str:
    if password_file is not None:
        return read_password_file(password_file)
    first = getpass.getpass("One-time password: ")
    second = getpass.getpass("Confirm one-time password: ")
    if first != second:
        raise ValueError("Passwords do not match")
    return first


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.users",
        description="Manage local LeadTrace accounts without exposing secrets in argv.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser("create", help="Create a local account")
    create.add_argument("username")
    create.add_argument("--display-name", required=True)
    create.add_argument("--role", choices=[role.value for role in UserRole], required=True)
    create.add_argument("--password-file", type=Path)

    reset = subcommands.add_parser("reset", help="Set a one-time password")
    reset.add_argument("user_id", type=UUID)
    reset.add_argument("--password-file", type=Path)

    disable = subcommands.add_parser("disable", help="Disable an account")
    disable.add_argument("user_id", type=UUID)

    enable = subcommands.add_parser("enable", help="Enable an account")
    enable.add_argument("user_id", type=UUID)

    role = subcommands.add_parser("role", help="Change an account role")
    role.add_argument("user_id", type=UUID)
    role.add_argument("role", choices=[item.value for item in UserRole])

    revoke = subcommands.add_parser("revoke", help="Force logout on all sessions")
    revoke.add_argument("user_id", type=UUID)

    subcommands.add_parser("list", help="List accounts without credential material")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    resources = bootstrap_database(settings)
    service = UserService()
    try:
        with transactional_session(resources.session_factory) as session:
            if args.command == "create":
                user = service.create_user(
                    session,
                    username=args.username,
                    display_name=args.display_name,
                    role=UserRole(args.role),
                    initial_password=_read_password(args.password_file),
                )
                print(f"created {user.id} {user.username} {user.role.value}")
            elif args.command == "reset":
                user = service.reset_password(
                    session,
                    args.user_id,
                    _read_password(args.password_file),
                )
                print(f"reset {user.id} {user.username}; password change required")
            elif args.command == "disable":
                user = service.set_enabled(session, args.user_id, False)
                print(f"disabled {user.id} {user.username}")
            elif args.command == "enable":
                user = service.set_enabled(session, args.user_id, True)
                print(f"enabled {user.id} {user.username}")
            elif args.command == "role":
                user = service.set_role(session, args.user_id, UserRole(args.role))
                print(f"role {user.id} {user.username} {user.role.value}")
            elif args.command == "revoke":
                revoked = service.revoke_sessions(session, args.user_id)
                print(f"revoked {revoked} session(s) for {args.user_id}")
            elif args.command == "list":
                for user in service.list_users(session):
                    state = "enabled" if user.is_enabled else "disabled"
                    print(f"{user.id} {user.username} {user.role.value} {state}")
            else:
                parser.error("Unknown command")
    finally:
        resources.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
