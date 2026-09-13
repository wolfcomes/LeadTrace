# Optional Password Change and Default Accounts Design

**Status:** Approved on 2026-09-13

## Goal

Remove the mandatory first-login password-change gate while keeping voluntary,
authenticated password changes available from the signed-in account area. New
accounts use one server-configured local default password, and an explicit
one-time operation resets existing Reviewer and Visitor accounts to that
default without changing any existing Admin password.

## Authentication behavior

Login succeeds directly into the role-appropriate application area. The
historical `must_change_password` field remains in the database and response
schemas for compatibility, but it no longer participates in route guards,
permission evaluation, maintenance checks, or domain mutation checks. New
accounts and password resets persist the flag as `false`.

The existing authenticated password-change endpoint remains the only self-
service password-change path. It continues to require the current password, a
valid authenticated session, and CSRF protection; success rotates the session
and revokes the previous session. Passwords remain Argon2id hashes and the
relaxed minimum length is six characters.

## Default-password boundary

The shared default password is supplied as `LEADTRACE_DEFAULT_ACCOUNT_PASSWORD`
and represented by `SecretStr` in application settings. The value is never
returned by an API, rendered in the interface, included in an audit event, or
printed by a management command. Production-mode configuration must provide a
non-placeholder value of at least six characters, while tests provide an
isolated fixture value.

Admin account creation no longer accepts a client-selected initial password.
The server reads the configured default and hashes it with a fresh Argon2id
salt for every account. This applies to newly created Visitor, Reviewer, and
Admin accounts. Individual Admin-initiated password reset becomes “reset to
configured default” and retains CSRF and recent-reauthentication requirements.

The existing Admin account is excluded from the one-time corpus reset. The
bulk reset selects only `visitor` and `reviewer` roles under a transaction,
updates each password using a fresh hash, leaves all Admin credential fields
unchanged, clears the obsolete first-login flag, and revokes each affected
account's active sessions. The operation supports a dry run that reports only
role counts before an explicit apply.

## Frontend behavior

The public login page remains login-only. After authentication, the account
area in `AppShell` exposes a `修改密码` link for every role alongside sign-out.
The `/change-password` route becomes a normal authenticated route: it no longer
redirects users based on `must_change_password`, and its copy describes an
optional account action rather than a first-login requirement.

The Admin Users page removes the initial-password input. Creating an account
sends username, display name, and role only. Each account row exposes a
confirmed `重置为默认密码` action. Neither creation nor reset reveals the
configured default in the browser.

## Audit and failure handling

Account creation, individual default reset, and the one-time non-Admin reset
record append-only audit events containing actor, target account, result, and
request metadata but no credential material. Password resets revoke target
sessions in the same transaction. A missing default-password configuration
fails before any account is inserted or modified.

Web and CLI account creation/reset use the same locked service operations. The
first Admin is created only through an explicit bootstrap mode on an empty user
database and its audit event is self-attributed. Every later CLI create/reset
requires the identifier of an enabled Admin. Individual reset audit state is
captured after locking the latest user row and includes a timestamp change plus
the aggregate number of sessions revoked, never a session identifier.

The bulk command is safe by construction: its database predicate excludes the
Admin role, its default mode is dry-run, and `--apply` plus an enabled Admin
actor is required for mutation. A transaction failure rolls back password
updates, session revocations, and audit events together.

## Compatibility and rollout

No schema column is removed in this phase. Keeping the legacy field avoids a
large migration and preserves compatibility with existing clients while the
server and current Vue client stop using it as a gate. The rollout sequence is:

1. configure the approved default through the service environment;
2. deploy the backend and frontend changes;
3. run the bulk command in dry-run mode and confirm that only Reviewer and
   Visitor counts are present;
4. run the explicit apply operation;
5. verify the current Admin password still works and one representative
   non-Admin account can log in with the configured default; and
6. verify the representative account can voluntarily change its password from
   the signed-in account area.

## Verification

Backend tests cover six-character passwords, direct login without a mandatory
change gate, authorization for a legacy `must_change_password=true` principal,
server-side default account creation, individual default reset, session
revocation, missing configuration, bulk dry-run/apply behavior, Admin
exclusion, and credential-free audit details.

Frontend tests cover normal post-login routing for legacy flag values, direct
authenticated access to the password-change page, the signed-in account link,
the absence of a password field during Admin creation, and the confirmed
default-reset action. Full backend and frontend suites, type checking, build,
and migration checks must pass before the acceptance data operation runs.
