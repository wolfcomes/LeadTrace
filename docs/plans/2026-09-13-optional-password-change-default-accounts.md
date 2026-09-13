# Optional Password Change and Default Accounts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove mandatory first-login password changes, expose voluntary password changes after login, provision new accounts from a server-side default, and reset existing non-Admin accounts without changing existing Admin credentials.

**Architecture:** Keep the legacy `must_change_password` field for compatibility but remove it from authorization and navigation decisions. Read the shared default from a `SecretStr` runtime setting, use it only inside account services, and provide a dry-run-first management command whose database predicate excludes Admin users. Preserve Argon2id, CSRF, session rotation/revocation, login throttling, and recent Admin reauthentication.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Pydantic Settings, Argon2id, pytest, Vue 3, TypeScript, Pinia, Vue Router, Vitest.

---

### Task 1: Relax the local password policy to six characters

**Files:**
- Modify: `leadtrace/backend/tests/auth/test_passwords.py`
- Modify: `leadtrace/backend/tests/auth/test_auth_api.py`
- Modify: `leadtrace/backend/app/security/passwords.py`
- Modify: `leadtrace/frontend/tests/auth.spec.ts`
- Modify: `leadtrace/frontend/tests/admin.spec.ts`
- Modify: `leadtrace/frontend/src/auth/ChangePasswordPage.vue`
- Modify: `leadtrace/frontend/src/admin/UsersPage.vue`

**Step 1: Preserve and review the existing failing tests**

Keep the already-written assertions that simple six-character values pass,
shorter values fail, a six-character password survives a real change/logout/
login flow, and relevant password inputs use `minlength="6"`.

**Step 2: Run the focused tests to verify RED**

Run with only the isolated database environment configured:

```bash
cd leadtrace/backend
env -i PATH="$PATH" \
  LEADTRACE_TEST_DATABASE_URL="$LEADTRACE_TEST_DATABASE_URL" \
  ../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/auth/test_passwords.py tests/auth/test_auth_api.py -q
```

Run:

```bash
cd leadtrace/frontend
npm test -- auth.spec.ts admin.spec.ts
```

Expected: the backend rejects six-character values under the old 16-character
mixed-class policy, and the frontend reports missing `minlength` attributes.

**Step 3: Implement the minimum policy**

Replace `validate_password` with a single `len(password) < 6` check and the
message `Password must contain at least 6 characters`. Keep the Argon2id
hasher parameters and verification logic unchanged. Add `minlength="6"` to
the new-password and confirm-password inputs and to the existing Admin
password input, which Task 4 will later remove.

**Step 4: Run focused tests to verify GREEN**

Repeat Step 2. Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add leadtrace/backend/app/security/passwords.py \
  leadtrace/backend/tests/auth/test_passwords.py \
  leadtrace/backend/tests/auth/test_auth_api.py \
  leadtrace/frontend/src/auth/ChangePasswordPage.vue \
  leadtrace/frontend/src/admin/UsersPage.vue \
  leadtrace/frontend/tests/auth.spec.ts \
  leadtrace/frontend/tests/admin.spec.ts
git commit -m "feat: allow simple local passwords"
```

### Task 2: Remove the mandatory password-change authorization gate

**Files:**
- Modify: `leadtrace/backend/tests/security/test_permissions.py`
- Modify: `leadtrace/backend/tests/auth/test_auth_api.py`
- Modify: `leadtrace/backend/tests/auth/test_users.py`
- Modify: `leadtrace/backend/app/security/policies.py`
- Modify: `leadtrace/backend/app/users/models.py`
- Modify: `leadtrace/backend/app/users/service.py`
- Modify: `leadtrace/backend/app/activities/router.py`
- Modify: `leadtrace/backend/app/compounds/router.py`
- Modify: `leadtrace/backend/app/evidence/router.py`
- Modify: `leadtrace/backend/app/imports/service.py`
- Modify: `leadtrace/backend/app/jobs/router.py`
- Modify: `leadtrace/backend/app/lineages/router.py`
- Modify: `leadtrace/backend/app/maintenance/service.py`
- Modify: `leadtrace/backend/app/releases/router.py`
- Modify: `leadtrace/backend/app/reviews/router.py`
- Modify: `leadtrace/backend/app/structures/router.py`
- Modify: `leadtrace/backend/app/visual_objects/router.py`
- Modify: `leadtrace/backend/app/visual_objects/objects_router.py`

**Step 1: Write failing backend behavior tests**

Replace `test_first_login_principal_is_limited_until_password_change` with a
test that constructs `Principal(..., must_change_password=True)` and asserts
that the normal role/resource matrix still applies. Update login and user
service assertions so newly created and reset users return
`must_change_password=False`.

Add an authenticated API assertion demonstrating that a legacy database user
whose flag is still true can access an endpoint permitted to that role. This
proves the obsolete flag is not merely hidden in the frontend.

**Step 2: Run focused tests to verify RED**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/security/test_permissions.py tests/auth/test_auth_api.py \
  tests/auth/test_users.py -q
```

Expected: permission evaluation still returns `Password change required`, and
new/reset users still have the flag set.

**Step 3: Remove every production gate**

Delete the early `principal.must_change_password` rejection from policy
evaluation and direct routers. Remove the flag from maintenance eligibility
logic. Change the model default and `UserService.create_user`/
`reset_password` assignments to `false`. Keep the response field and the
`change_password` assignment for compatibility.

Use:

```bash
rg -n "must_change_password" leadtrace/backend/app
```

Classify every remaining match. Only model/schema compatibility, response
serialization, release-import compatibility, and assignments to `false` may
remain; no authorization branch may remain.

**Step 4: Run focused and route-security tests to verify GREEN**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/security/test_permissions.py \
  tests/security/test_route_permission_matrix.py \
  tests/auth/test_auth_api.py tests/auth/test_users.py -q
```

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add leadtrace/backend/app leadtrace/backend/tests/auth \
  leadtrace/backend/tests/security/test_permissions.py
git commit -m "feat: make password changes optional"
```

### Task 3: Make password changes a signed-in account action

**Files:**
- Modify: `leadtrace/frontend/tests/auth.spec.ts`
- Modify: `leadtrace/frontend/tests/navigation.spec.ts`
- Modify: `leadtrace/frontend/src/auth/LoginPage.vue`
- Modify: `leadtrace/frontend/src/auth/ChangePasswordPage.vue`
- Modify: `leadtrace/frontend/src/app/router.ts`
- Modify: `leadtrace/frontend/src/app/AppShell.vue`
- Modify: `leadtrace/frontend/src/i18n/zh-CN.ts`

**Step 1: Write failing navigation tests**

Change the first-login test to return `must_change_password: true` and assert
that successful login follows the requested/default destination instead of
`/change-password`. Add tests that:

- a signed-in user can navigate directly to `/change-password`;
- the account area contains a `修改密码` link to that route; and
- the public login page contains no password-change control.

**Step 2: Run the tests to verify RED**

Run:

```bash
cd leadtrace/frontend
npm test -- auth.spec.ts navigation.spec.ts
```

Expected: legacy flags still redirect, the route rejects normal users, and the
account link is absent.

**Step 3: Implement optional navigation**

Remove flag-based branching from `LoginPage` and the global router guard.
Declare `/change-password` as a normal authenticated route available to every
role. Add a `RouterLink` beside sign-out in `AppShell` and update Chinese copy
from mandatory first-login language to voluntary account-security language.

**Step 4: Run frontend tests and type checking**

Run:

```bash
cd leadtrace/frontend
npm test -- auth.spec.ts navigation.spec.ts
npm run typecheck
```

Expected: tests and type checking pass.

**Step 5: Commit**

```bash
git add leadtrace/frontend/src leadtrace/frontend/tests/auth.spec.ts \
  leadtrace/frontend/tests/navigation.spec.ts
git commit -m "feat: expose voluntary password changes"
```

### Task 4: Provision and reset accounts from the server default

**Files:**
- Modify: `leadtrace/backend/app/config.py`
- Modify: `leadtrace/backend/app/users/schemas.py`
- Modify: `leadtrace/backend/app/users/router.py`
- Modify: `leadtrace/backend/tests/auth/test_auth_api.py`
- Modify: `leadtrace/backend/tests/security/test_route_permission_matrix.py`
- Modify: `leadtrace/frontend/src/admin/api.ts`
- Modify: `leadtrace/frontend/src/admin/UsersPage.vue`
- Modify: `leadtrace/frontend/tests/admin.spec.ts`

**Step 1: Write failing configuration and API tests**

Construct test `Settings` with a fixture-only `default_account_password`.
Change account-creation tests to omit `initial_password`, then log in with the
configured default and assert the response never contains it. Change reset
tests to send no password body, verify the old password stops working, verify
the configured default works, and verify prior sessions are revoked.

Add a test that missing configuration returns a safe service-unavailable error
before inserting or changing an account. Keep CSRF and recent Admin
reauthentication assertions.

**Step 2: Run backend tests to verify RED**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/auth/test_auth_api.py \
  tests/security/test_route_permission_matrix.py -q
```

Expected: request schemas require client password fields and settings do not
provide a server default.

**Step 3: Implement the server-side contract**

Add:

```python
default_account_password: SecretStr | None = None
```

to `Settings`, require a non-placeholder value of at least six characters in
production, and
add a private router helper that returns the secret or raises a safe 503.
Remove password fields from `UserCreateRequest` and `PasswordResetRequest`.
Pass the configured secret into the existing user service for create/reset.
Do not include it in exceptions, response models, audit details, or logs.

**Step 4: Write failing Admin UI tests**

Assert that the creation form has no password input and sends only username,
display name, and role. Assert that each row offers `重置为默认密码`, requires
confirmation, and calls the bodyless reset endpoint.

**Step 5: Run frontend tests to verify RED**

Run:

```bash
cd leadtrace/frontend
npm test -- admin.spec.ts
```

Expected: the form still requires a password and there is no reset action.

**Step 6: Implement the Admin UI**

Add a typed `resetUserToDefault(id)` client method. Remove `newPassword` and
the password input from `UsersPage`; add role selection if absent; add the
confirmed row-level reset action. Display only success/error status and never
the default value.

**Step 7: Verify GREEN and commit**

Run the backend and frontend commands above, then:

```bash
git add leadtrace/backend/app/config.py leadtrace/backend/app/users \
  leadtrace/backend/tests/auth/test_auth_api.py \
  leadtrace/backend/tests/security/test_route_permission_matrix.py \
  leadtrace/frontend/src/admin leadtrace/frontend/tests/admin.spec.ts
git commit -m "feat: use server default for managed accounts"
```

### Task 5: Add a dry-run-first non-Admin credential reset

**Files:**
- Modify: `leadtrace/backend/app/users/service.py`
- Modify: `leadtrace/backend/app/cli/users.py`
- Modify: `leadtrace/backend/tests/auth/test_users.py`
- Modify: `leadtrace/backend/tests/auth/test_cli.py`
- Modify: `leadtrace/backend/app/audit/service.py` only if a credential-safe
  user-state hashing helper is needed

**Step 1: Write failing service tests**

Seed one existing Admin, Reviewer, and Visitor with distinct password hashes
and active sessions. Call the proposed bulk service in dry-run mode and assert
no fields or sessions change. Call apply and assert:

```python
assert result.role_counts == {"reviewer": 1, "visitor": 1}
assert admin.password_hash == original_admin_hash
assert verify_password(reviewer.password_hash, configured_default)
assert verify_password(visitor.password_hash, configured_default)
assert not active_non_admin_sessions
```

Also assert all affected flags are false and every audit detail is free of
password values and password hashes.

**Step 2: Run service tests to verify RED**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/auth/test_users.py -q
```

Expected: the bulk operation does not exist.

**Step 3: Implement the transactional service**

Add a result dataclass containing only counts and affected IDs. Select users
with `User.role.in_([UserRole.REVIEWER, UserRole.VISITOR])` and
`with_for_update()`. Dry-run computes counts only. Apply hashes the configured
default independently per account, sets the compatibility flag false, records
`password_changed_at`, revokes sessions, and appends credential-free audit
events attributed to the explicit Admin actor.

Reject a missing, disabled, or non-Admin actor before locking targets. Never
accept a role list from command-line input; the non-Admin predicate is fixed in
production code.

**Step 4: Write and verify failing CLI tests**

Add parser/unit tests showing `reset-non-admin-default` is dry-run by default,
requires an Admin actor identifier, accepts `--apply`, does not accept a
plaintext password argument, and prints counts only.

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest tests/auth/test_cli.py -q
```

Expected: the new command is missing.

**Step 5: Implement the CLI wrapper**

Read the default only from `Settings.default_account_password`. Print a stable
summary containing `mode`, `reviewer_count`, and `visitor_count`. Do not print
usernames, password values, hashes, tokens, connection strings, or session
data. Require `--apply` for mutation.

Route both Web and CLI managed create/reset operations through locked service
methods that append credential-free audit events. CLI creation must use either
explicit first-Admin `--bootstrap` on an empty database or an enabled Admin
`--actor-id`; CLI individual reset always requires `--actor-id`. Capture the
single-reset before state only after locking and record the actual aggregate
session revocation count.

**Step 6: Verify GREEN and commit**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/auth/test_users.py tests/auth/test_cli.py \
  tests/audit/test_audit.py -q
```

Then commit:

```bash
git add leadtrace/backend/app/users/service.py \
  leadtrace/backend/app/cli/users.py \
  leadtrace/backend/app/audit/service.py \
  leadtrace/backend/tests/auth/test_users.py \
  leadtrace/backend/tests/auth/test_cli.py
git commit -m "feat: reset non-admin accounts safely"
```

### Task 6: Integrate, verify, and prepare the controlled acceptance update

**Files:**
- Modify: `docs/plans/2026-09-13-admin-review-workflow-completion-design.md`
- Modify: `docs/plans/2026-09-13-admin-review-workflow-completion.md`
- Modify: deployment environment outside Git only when applying acceptance

**Step 1: Update superseded documentation**

Replace statements that Admin-created/reset passwords are one-time or require
first-login change with the approved optional-flow design. Link to the focused
design and implementation plan. Keep the minimum-six policy and all remaining
security controls accurate.

**Step 2: Run full verification in the isolated database**

Read and follow `superpowers:verification-before-completion`, then run with
only the isolated test database URL preserved:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest -q
../../../leadtrace-platform/.venv/bin/python -m ruff check app tests
../../../leadtrace-platform/.venv/bin/python -m compileall -q app
```

Run:

```bash
cd leadtrace/frontend
npm test
npm run typecheck
npm run build
```

Run `git diff --check` and verify no secret is tracked by Git.

**Step 3: Commit documentation and integration fixes**

```bash
git add docs leadtrace
git commit -m "docs: align account workflow with optional password changes"
```

**Step 4: Prepare but do not silently apply acceptance data mutation**

Configure `LEADTRACE_DEFAULT_ACCOUNT_PASSWORD` in the non-versioned service
environment without printing it. Restart only the FastAPI/frontend services
that require the new configuration; do not stop PostgreSQL, Redis, Caddy, the
legacy Dashboard, or the user Vite process.

Run the bulk command without `--apply`, capture only role counts, and verify
that no Admin count is present. Run `--apply` only after the code review and
full verification checkpoints have passed. Confirm the existing Admin
credential hash is byte-for-byte unchanged before and after, without printing
the hash.

**Step 5: Report the acceptance checkpoint**

Report code/test status, the number of Reviewer/Visitor accounts affected,
Admin exclusion verification, and whether the acceptance reset was applied.
Never report the password, password hash, cookies, CSRF tokens, session secret,
or database URL.
