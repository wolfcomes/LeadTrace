# User-Managed LeadTrace Cutover Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the verified paper-centric Pilot from temporary acceptance infrastructure to a persistent user-owned PostgreSQL/Redis/Caddy stack and expose it to controlled LAN clients at `https://10.21.53.251:8876` without administrator privileges.

**Architecture:** Restore the verified encrypted Pilot database and managed assets into a new persistent PostgreSQL 16 cluster below `leadtrace-data/production/`, run a dedicated user-owned Redis/Web/Celery stack, and use Caddy's internal CA for an IP-SAN HTTPS route. Preserve the current legacy Caddy, Dashboard, and database until post-cutover smoke and route-only rollback tests pass.

**Tech Stack:** PostgreSQL 16 (`initdb`, `pg_ctl`, `pg_restore`), Redis 7, FastAPI/Uvicorn, Celery, Caddy 2.11 internal PKI, user crontab, Python/HTTPX smoke tests, existing LeadTrace preflight and backup/restore tooling.

---

### Task 1: Create the persistent user-owned production root

**Files:**
- Create outside Git: `leadtrace-data/production/`
- Create outside Git: `leadtrace-data/production/secrets/`
- Create outside Git: `leadtrace-data/production/run/`
- Create outside Git: `leadtrace-data/production/logs/`

**Step 1: Create directories with restrictive modes**

Run a shell command that creates the production tree below the existing
`leadtrace-data` root, sets directories to `0700`, and refuses to continue if
the path resolves outside the project data root.

Expected: all production directories exist and are owned by the current user.

**Step 2: Create a protected runtime environment file**

Write database credentials, Redis authentication, session secret, asset root,
Source root, and exact application commit to a `0600` file outside Git.

Expected: no secret appears in Git status, shell history, or logs.

**Step 3: Verify isolation**

Run `realpath`, `stat`, and process/database identity checks. Confirm the new
production database name and ports differ from `leadtrace_acceptance`, the
temporary `55444` cluster, and the old Web process.

Expected: all identities are distinct; stop on any ambiguity.

**Step 4: Commit the operations documentation only**

```bash
git add docs/plans/2026-09-18-user-managed-leadtrace-cutover.md
git commit -m "docs: plan user-managed LeadTrace cutover"
```

### Task 2: Provision durable PostgreSQL and restore the Pilot

**Files:**
- Create outside Git: `leadtrace-data/production/postgres/data/`
- Create outside Git: `leadtrace-data/production/postgres/postgresql.conf`
- Create outside Git: `leadtrace-data/production/postgres/pg_hba.conf`
- Create outside Git: `leadtrace-data/production/postgres/start.sh`

**Step 1: Initialize a fresh PostgreSQL 16 cluster**

Run `initdb` with local peer authentication and host SCRAM authentication in
the persistent data directory. Configure a loopback high port and no external
listen address.

Expected: `pg_ctl ... status` succeeds and the cluster is not `/tmp`.

**Step 2: Create the new production database identity**

Start the cluster, create a separately named database, and record its resolved
host, port, database name, and current schema state without recording secrets.

Expected: the new database is empty before restore and is not the legacy or
acceptance database.

**Step 3: Restore the verified candidate database backup**

Decrypt only into a protected temporary file, restore with PostgreSQL 16
`pg_restore`, and remove plaintext immediately after completion.

Expected: restore exits 0 and the database has Alembic head
`0025_ai_prefill_runs`.

**Step 4: Restore managed assets**

Decrypt the matching full asset archive into the persistent asset root and
validate its manifest. Keep Source PDFs in their read-only namespace.

Expected: exactly 22 assets match size and SHA-256.

**Step 5: Verify database and asset integrity**

Run the existing aggregate verifier against the persistent targets. Require 20
Papers, 20 PaperSources, 39 Change Events, 3 submissions, 2 published versions,
zero integrity defects, and one enabled Admin.

Expected: the aggregate matches `expected-aggregate.json`.

### Task 3: Provision user-level Redis, Web, and Celery

**Files:**
- Create outside Git: `leadtrace-data/production/redis/redis.conf`
- Create outside Git: `leadtrace-data/production/run/start-stack.sh`
- Create outside Git: `leadtrace-data/production/run/stop-stack.sh`
- Create outside Git: `leadtrace-data/production/run/status-stack.sh`

**Step 1: Start isolated Redis**

Use the existing Redis 7 binary, a production-only port and data directory,
append-only persistence, and a protected authentication secret.

Expected: `redis-cli ping` returns `PONG` and no keys are shared with the
acceptance Redis namespace.

**Step 2: Start Web and Worker with persistent identities**

Run the exact tested application commit with the persistent database URL,
Redis URL, managed asset root, read-only Source root, and application commit.

Expected: Web health/ready returns 200 and Celery inspect returns `pong`.

**Step 3: Add idempotent user-level lifecycle controls**

Implement lock/PID checks, readiness polling, graceful stop, and safe restart.
The lifecycle script must refuse duplicate processes and must never stop the
legacy Web, Dashboard, or old Caddy by pattern matching.

Expected: start twice is safe, stop only affects production PIDs, and status
shows all component identities without secrets.

**Step 4: Run a user-level restart drill**

Stop and restart only the new stack, then re-run health, Redis, worker, and
database probes.

Expected: the stack returns to ready without administrator privileges.

### Task 4: Generate user-owned HTTPS and client onboarding

**Files:**
- Create outside Git: `leadtrace-data/production/caddy/Caddyfile`
- Create outside Git: `leadtrace-data/production/client-trust/leadtrace-root.crt`
- Create outside Git: `leadtrace-data/production/client-trust/leadtrace-root.sha256`
- Create outside Git: `leadtrace-data/production/client-trust/README.md`

**Step 1: Generate Caddy internal-CA state**

Configure Caddy `tls internal` for the `10.21.53.251` site and keep the CA key
under the protected production Caddy directory.

Expected: the issued certificate contains IP SAN `10.21.53.251`, is not expired,
and the private key is mode `0600`.

**Step 2: Stage the application Caddy route**

Proxy `/api/*` and `/health/*` to persistent Web, serve the commit-specific
frontend, and retain a GET-only `/legacy-dashboard/` fallback. Validate the
configuration before binding `:8876`.

Expected: Caddy validation succeeds without touching the running old Caddy.

**Step 3: Create the temporary certificate bootstrap endpoint**

Serve only `leadtrace-root.crt` and its fingerprint on a separate high port,
with no application routes or credentials. Document Linux, macOS, and Windows
trust-store import commands.

Expected: a controlled client can download the public root, verify its SHA-256,
and import it without receiving a private key.

### Task 5: Fresh persistent preflight

**Files:**
- Create outside Git: `leadtrace-data/production/preflight-config.json`
- Create outside Git: `leadtrace-data/production/preflight-report.json`
- Modify only if needed: `leadtrace/ops/cutover/preflight.py`
- Test: `leadtrace/backend/tests/ops/test_paper_centric_preflight.py`

**Step 1: Bind preflight to persistent identities**

Point the existing preflight configuration at the persistent database, asset
root, Caddy loopback listener, fresh backups, restore report, acceptance
evidence, and fixed Pilot Manifest.

Expected: no field points at `/tmp`, the legacy database, or the acceptance
database.

**Step 2: Run all eight preflight checks**

Run the existing preflight with the exact tested commit and protected role
credentials.

Expected: database backup, asset backup, restore drill, acceptance evidence,
database, services, permissions, and source manifest are all `PASS`.

**Step 3: Run focused and full verification**

Run the preflight tests, audit CLI, frontend tests/build, and selected Playwright
smoke tests against the persistent stack.

Expected: no failures and no Source PDF changes.

### Task 6: Approved route switch and smoke tests

**Files:**
- Create outside Git: `leadtrace-data/production/caddy/legacy-Caddyfile.previous`
- Create outside Git: `leadtrace-data/production/cutover-record.md`
- Create outside Git: `leadtrace-data/production/smoke-after-cutover.json`
- Create outside Git: `leadtrace-data/production/smoke-after-fallback.json`

**Step 1: Take final rollback backups**

Record the old Caddy config and final rollback backup IDs. Do not alter the
legacy database schema or data.

Expected: rollback artifacts verify before any route change.

**Step 2: Switch Caddy atomically**

Stop only the old Caddy PID, validate the production Caddyfile, and start the
new user-owned Caddy on `10.21.53.251:8876`.

Expected: the old Web and Dashboard remain running; the new route answers HTTPS.

**Step 3: Run post-cutover smoke tests**

Verify health, Visitor, Reviewer, Admin, authorized PDF range access, audit
verification, and read-only legacy fallback from the server and a controlled
LAN client.

Expected: all smoke checks pass with the client root CA.

**Step 4: Exercise route-only fallback**

Restore the preserved legacy Caddy configuration, verify old Dashboard GET and
denied write methods, then restore the new Caddy route and run a second smoke
test.

Expected: both routes can be selected without database restore or data loss.

### Task 7: Disable bootstrap and install reboot recovery

**Files:**
- Modify outside Git: `leadtrace-data/production/run/start-stack.sh`
- Modify outside Git: `leadtrace-data/production/client-trust/README.md`
- Modify user crontab with a marked entry

**Step 1: Onboard controlled clients**

Have each approved LAN client download the root certificate, verify the
fingerprint, import it, and run the HTTPS health check.

Expected: at least one client succeeds before disabling bootstrap.

**Step 2: Release the certificate bootstrap port**

Stop the certificate-only endpoint and verify the port is no longer listening.

Expected: only the HTTPS application route remains externally reachable.

**Step 3: Install the idempotent `@reboot` entry**

Back up the current user crontab, add one marked startup entry, and verify that
running it manually does not duplicate processes.

Expected: reboot recovery is user-owned and the legacy services remain intact.

### Task 8: Record completion and preserve rollback evidence

**Files:**
- Modify outside Git: `leadtrace-data/production/cutover-record.md`
- Create outside Git: `leadtrace-data/production/completion-report.json`

**Step 1: Hash final evidence**

Hash the persistent preflight, restore report, backups, Caddy certificate,
client root, and both smoke reports.

Expected: all hashes are recorded without credentials, cookies, private keys, or
absolute protected Source paths.

**Step 2: Verify repository safety**

Run `git diff --check`, `git status`, and Source/Dashboard unchanged probes.

Expected: only intentional documentation commits exist; no runtime secret or
asset is tracked.

**Step 3: Commit implementation documentation**

```bash
git add docs/plans/2026-09-18-user-managed-leadtrace-cutover.md
git commit -m "docs: plan user-managed LeadTrace cutover"
```

Expected: the branch records the implementation plan while all runtime
artifacts remain outside Git.
