from __future__ import annotations

import argparse
from uuid import UUID, uuid4

from app.config import Settings, get_settings
from app.database import bootstrap_database, transactional_session
from app.users.models import UserRole
from app.users.service import UserService


def _configured_default_password(settings: Settings) -> str:
    configured = settings.default_account_password
    if configured is None:
        raise RuntimeError("LEADTRACE_DEFAULT_ACCOUNT_PASSWORD is required")
    return configured.get_secret_value()


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
    creation_authority = create.add_mutually_exclusive_group(required=True)
    creation_authority.add_argument("--actor-id", type=UUID)
    creation_authority.add_argument("--bootstrap", action="store_true")

    reset = subcommands.add_parser("reset", help="Reset to the configured default")
    reset.add_argument("user_id", type=UUID)
    reset.add_argument("--actor-id", type=UUID, required=True)

    reset_non_admin = subcommands.add_parser(
        "reset-non-admin-default",
        help="Preview or reset all Reviewer and Visitor accounts",
    )
    reset_non_admin.add_argument("--actor-id", type=UUID, required=True)
    reset_non_admin.add_argument("--apply", action="store_true")

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
    service = UserService()
    configured_default = None
    if args.command in {"create", "reset", "reset-non-admin-default"}:
        configured_default = _configured_default_password(settings)
    resources = bootstrap_database(settings)
    try:
        with transactional_session(resources.session_factory) as session:
            if args.command == "create":
                if args.bootstrap:
                    if UserRole(args.role) is not UserRole.ADMIN:
                        parser.error("--bootstrap can create only an Admin account")
                    user = service.bootstrap_admin(
                        session,
                        username=args.username,
                        display_name=args.display_name,
                        default_password=configured_default,
                        request_id=f"cli-account-bootstrap-{uuid4()}",
                    )
                else:
                    user = service.create_managed_user(
                        session,
                        actor_id=args.actor_id,
                        username=args.username,
                        display_name=args.display_name,
                        role=UserRole(args.role),
                        default_password=configured_default,
                        request_id=f"cli-account-create-{uuid4()}",
                    )
                print(f"created {user.id} {user.username} {user.role.value}")
            elif args.command == "reset":
                result = service.reset_managed_password(
                    session,
                    actor_id=args.actor_id,
                    user_id=args.user_id,
                    default_password=configured_default,
                    request_id=f"cli-account-reset-{uuid4()}",
                )
                user = result.user
                print(f"reset {user.id} {user.username}")
            elif args.command == "reset-non-admin-default":
                result = service.reset_non_admin_passwords_to_default(
                    session,
                    actor_id=args.actor_id,
                    default_password=configured_default,
                    apply=args.apply,
                    request_id=f"cli-account-reset-{uuid4()}",
                )
                mode = "apply" if result.applied else "dry-run"
                print(
                    f"mode={mode} "
                    f"reviewer_count={result.role_counts[UserRole.REVIEWER]} "
                    f"visitor_count={result.role_counts[UserRole.VISITOR]}"
                )
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
