# LeadTrace Paper-Centric Cutover Runbook

## Scope

This runbook moves the LAN route from the preserved legacy service to a staged
Paper-centric LeadTrace candidate. The candidate owns a new PostgreSQL database,
a separate managed-asset root, and version-matched web and worker processes. The
currently routed database is never migrated in place.

Only an authorized operations operator and Admin approver may conduct the
cutover. The route may change only in an explicitly approved maintenance window.
Until that window, keep `:8876`, the legacy database, and the read-only Dashboard
on `127.0.0.1:8765` unchanged.

## Safety rules

- Never run Alembic against the currently routed database.
- Never point a candidate process at the legacy database or asset root.
- Never modify `source_pdfs/`; it is read-only input identified by the checked-in
  20-Paper Pilot Manifest.
- Never treat an acceptance JSON `PASS` value as sufficient evidence. Verify its
  hash, referenced screenshots, database records, backups, and restore report.
- Never label a backup destination `separate_disk` unless it is on a physically
  independent filesystem or controlled network destination.
- Stop on every failed gate. Do not weaken a gate, edit evidence in place, or
  switch the primary route to investigate a failure.

## Record the change

Before staging, record the operator, Admin approver, proposed window, exact Git
commit, application version, Alembic head, current route, legacy database
identity, and candidate database identity in the protected operations record.
Do not record credentials, database URLs, cookies, tokens, or absolute Source
paths in repository documents.

Confirm:

- the old Dashboard answers at `http://127.0.0.1:8765` in read-only mode;
- the current `:8876` route is healthy and its process/database identities are
  known;
- one Admin, one assigned Reviewer, one unassigned Paper, one draft Workspace,
  and one Visitor account are available for the permission matrix;
- the candidate backup destination is physically independent;
- the staged TLS certificate covers the loopback hostname or address used by
  the preflight listener.

## Build the selected commit

Build and test from the exact commit recorded for the candidate:

```bash
cd leadtrace/frontend
npm ci --no-audit --no-fund
npm run typecheck
npm test -- --run
npm run test:ketcher-csp
```

`test:ketcher-csp` always runs the production build before the Chromium CSP
test, so the browser cannot silently exercise a stale ignored `dist/` tree. It
uses the self-contained E2E fixture and does not start the Vite development
server.

Install `dist/` into a new commit-specific directory below
`/srv/leadtrace/releases/<git-commit>/frontend`. Preserve the previous release
directory. Do not repoint the LAN-facing frontend symlink yet.

## Scope Ketcher security headers

The main application must keep its strict CSP and deny framing. Ketcher is a
separate same-origin document because its standalone WebAssembly runtime needs
dynamic evaluation and Blob Workers. Apply the relaxed policy to the exact
`/ketcher.html` response only; never apply it to `/assets/*`, the SPA
fallback, or an entire site block.

For a Caddy deployment, keep the response-header removals global, then use
mutually exclusive exact-path and not-path matchers for framing and CSP. The
strict matcher must explicitly exclude `/ketcher.html` so its `DENY` and strict
CSP headers do not overwrite the Ketcher response:

```caddyfile
@ketcher path /ketcher.html
@leadtraceMain not path /ketcher.html

header {
    -X-Powered-By
    -Server
}

header @leadtraceMain {
    X-Content-Type-Options "nosniff"
    X-Frame-Options "DENY"
    Referrer-Policy "same-origin"
    Permissions-Policy "camera=(), geolocation=(), microphone=()"
    Strict-Transport-Security "max-age=31536000"
    Content-Security-Policy "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
}

header @ketcher {
    X-Content-Type-Options "nosniff"
    X-Frame-Options "SAMEORIGIN"
    Referrer-Policy "same-origin"
    Permissions-Policy "camera=(), geolocation=(), microphone=()"
    Strict-Transport-Security "max-age=31536000"
    Content-Security-Policy "default-src 'self'; connect-src 'self' blob:; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'; worker-src 'self' blob:; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'"
}
```

Before any maintenance-window reload, build a standalone staged Caddyfile for
the exact candidate frontend release and exercise it with a temporary Caddy
process. The following full preflight configuration binds only to loopback
`:18878`; its admin API binds only to loopback `:20199`. Neither port conflicts
with the later Nginx candidate listener on `:8877`. Replace `<git-commit>` with
the recorded commit before running this block:

```bash
(
set -euo pipefail

export LEADTRACE_FRONTEND_RELEASE="/srv/leadtrace/releases/<git-commit>/frontend"
test -f "$LEADTRACE_FRONTEND_RELEASE/index.html"
test -f "$LEADTRACE_FRONTEND_RELEASE/ketcher.html"

caddy_stage_dir="$(mktemp -d /tmp/leadtrace-caddy-preflight.XXXXXX)"
candidate_caddyfile="$caddy_stage_dir/Caddyfile"
caddy_log="$caddy_stage_dir/caddy.log"
caddy_pid=""
export XDG_DATA_HOME="$caddy_stage_dir/data"
export XDG_CONFIG_HOME="$caddy_stage_dir/config"

cleanup_caddy_preflight() {
  if test -n "${caddy_pid:-}" && kill -0 "$caddy_pid" 2>/dev/null; then
    caddy stop --address 127.0.0.1:20199 || kill "$caddy_pid"
    wait "$caddy_pid" || true
  fi
  rm -rf -- "$caddy_stage_dir"
}
trap cleanup_caddy_preflight EXIT
trap 'exit 130' HUP INT TERM

cat >"$candidate_caddyfile" <<'CADDYFILE'
{
    admin 127.0.0.1:20199
    auto_https disable_redirects
    skip_install_trust
}

https://127.0.0.1:18878 {
    bind 127.0.0.1
    tls internal

    @ketcher path /ketcher.html
    @leadtraceMain not path /ketcher.html

    header {
        -X-Powered-By
        -Server
    }

    header @leadtraceMain {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "same-origin"
        Permissions-Policy "camera=(), geolocation=(), microphone=()"
        Strict-Transport-Security "max-age=31536000"
        Content-Security-Policy "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    }

    header @ketcher {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "same-origin"
        Permissions-Policy "camera=(), geolocation=(), microphone=()"
        Strict-Transport-Security "max-age=31536000"
        Content-Security-Policy "default-src 'self'; connect-src 'self' blob:; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'; worker-src 'self' blob:; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'"
    }

    root * {$LEADTRACE_FRONTEND_RELEASE}
    try_files {path} /index.html
    file_server
}
CADDYFILE

caddy validate --config "$candidate_caddyfile" --adapter caddyfile
caddy run --config "$candidate_caddyfile" --adapter caddyfile \
  >"$caddy_log" 2>&1 &
caddy_pid="$!"

candidate_origin="https://127.0.0.1:18878"
caddy_ready=false
for attempt in $(seq 1 30); do
  if curl -kfsS "$candidate_origin/" >/dev/null; then
    caddy_ready=true
    break
  fi
  kill -0 "$caddy_pid"
  sleep 0.2
done
test "$caddy_ready" = true

asset_file="$(find "$LEADTRACE_FRONTEND_RELEASE/assets" \
  -maxdepth 1 -type f -print -quit)"
test -n "$asset_file"
asset_url="${asset_file#"$LEADTRACE_FRONTEND_RELEASE"}"

main_headers="$(curl -kfsSI "$candidate_origin/")"
ketcher_headers="$(curl -kfsSI "$candidate_origin/ketcher.html")"
asset_headers="$(curl -kfsSI "$candidate_origin$asset_url")"

printf '%s\n' "$main_headers" | grep -Fi "script-src 'self';"
printf '%s\n' "$main_headers" | grep -Fi "frame-ancestors 'none'"
printf '%s\n' "$main_headers" | grep -Eiq '^x-frame-options:[[:space:]]*DENY'

printf '%s\n' "$ketcher_headers" | grep -Fi "script-src 'self' 'unsafe-eval'"
printf '%s\n' "$ketcher_headers" | grep -Fi "worker-src 'self' blob:"
printf '%s\n' "$ketcher_headers" | grep -Fi "frame-ancestors 'self'"
printf '%s\n' "$ketcher_headers" | \
  grep -Eiq '^x-frame-options:[[:space:]]*SAMEORIGIN'

printf '%s\n' "$asset_headers" | grep -Fi "script-src 'self';"
printf '%s\n' "$asset_headers" | grep -Fi "frame-ancestors 'none'"
printf '%s\n' "$asset_headers" | grep -Eiq '^x-frame-options:[[:space:]]*DENY'
! printf '%s\n' "$asset_headers" | \
  grep -Eiq "unsafe-eval|worker-src|SAMEORIGIN"

for headers in "$main_headers" "$ketcher_headers" "$asset_headers"; do
  ! printf '%s\n' "$headers" | grep -Eiq '^(server|x-powered-by):'
done

caddy stop --address 127.0.0.1:20199
wait "$caddy_pid"
caddy_pid=""
rm -rf -- "$caddy_stage_dir"
trap - EXIT HUP INT TERM
)
```

Require `script-src 'self'`, `frame-ancestors 'none'`, and
`X-Frame-Options: DENY` on the main response. Require
`script-src 'self' 'unsafe-eval'`, `worker-src 'self' blob:`,
`frame-ancestors 'self'`, and `X-Frame-Options: SAMEORIGIN` only on
`/ketcher.html`. The asset response must not contain the relaxed directives.
All three responses must omit `Server` and `X-Powered-By`. Any validation,
startup, curl, or assertion failure triggers the trap, stops only the temporary
Caddy process, removes its isolated state, and leaves the live route unchanged.
Do not bind this preflight to `:8876` or `:8877`; do not edit, reload, or stop
the live Caddy configuration outside the approved maintenance window. A failed
preflight is a stop gate, not authorization to alter the production route.

## Provision an isolated candidate

Provision a new empty PostgreSQL database and a new managed-asset root. The
database name should identify the cutover candidate and must not equal the name
used by the current route. Keep the URL in the protected process environment:

```bash
export LEADTRACE_CANDIDATE_DATABASE_URL='<protected candidate URL>'
export LEADTRACE_CANDIDATE_ASSET_ROOT='/var/lib/leadtrace-candidate/assets'
```

Before any migration, compare the resolved database host, port, and database
name against the running legacy service. Stop if any identity is ambiguous or
equal. Apply migrations only to the new candidate:

```bash
cd leadtrace/backend
LEADTRACE_DATABASE_URL="$LEADTRACE_CANDIDATE_DATABASE_URL" \\
  python -m alembic -c alembic.ini upgrade head
LEADTRACE_DATABASE_URL="$LEADTRACE_CANDIDATE_DATABASE_URL" \\
  python -m alembic -c alembic.ini current
```

The candidate database must now be at `0025_ai_prefill_runs` and contain no
Paper or scientific business rows. Create the one enabled Admin and the test
role accounts through the controlled account procedure.

## Import the fixed Pilot catalog

Use the protected Source root only as read-only input. Dry-run the checked-in
manifest before applying it to the candidate database:

```bash
LEADTRACE_DATABASE_URL="$LEADTRACE_CANDIDATE_DATABASE_URL" \\
  python -m app.cli.import_pilot \\
  --manifest ../../docs/pilot/2026-09-15-volume67-issue5-first20.json \\
  --source-root "$LEADTRACE_PILOT_SOURCE_ROOT" --dry-run

LEADTRACE_DATABASE_URL="$LEADTRACE_CANDIDATE_DATABASE_URL" \\
  python -m app.cli.import_pilot \\
  --manifest ../../docs/pilot/2026-09-15-volume67-issue5-first20.json \\
  --source-root "$LEADTRACE_PILOT_SOURCE_ROOT" --apply
```

Require exactly 20 verified PaperSources, 20 Papers, and 20 Source assets. Replay
the import once and require `created=0` and `unchanged=20`.

## Stage candidate services

Start the version-matched FastAPI and Celery processes with
`LEADTRACE_DATABASE_URL=$LEADTRACE_CANDIDATE_DATABASE_URL`, a candidate-specific
Redis namespace, and `LEADTRACE_ASSET_ROOT=$LEADTRACE_CANDIDATE_ASSET_ROOT`.
Bind FastAPI to an unused loopback port. Do not restart or repoint the processes
serving `:8876`.

Install the loopback-only TLS preflight listener on `:8877` and route it to the
candidate FastAPI/frontend. Validate the complete proxy configuration before a
reload:

```bash
sudo install -m 0644 leadtrace/deploy/nginx/nginx.native-preflight.conf \\
  /etc/nginx/conf.d/leadtrace-preflight.conf
sudo nginx -t
sudo nginx -s reload
```

Verify `https://127.0.0.1:8877/health/ready`. The listener is for isolated
candidate testing and must not alter the primary LAN route.

## Complete candidate acceptance

Against the candidate only, execute and record the manual Reviewer-to-Admin
approval path, AI-prefill path, request-changes/resubmission path, `not_reported`
section, invalid-Structure blocker, missing-Evidence blocker, and the forced
AI/Reviewer race. The Reviewer submission still requires Admin approval.

Capture desktop and mobile visual acceptance. The visual report must identify
the selected commit, report no browser/request errors, prove the PDF, Ketcher,
RDKit, and Lineage surfaces rendered, and include byte size and SHA-256 for each
relative screenshot path.

Update the protected `acceptance-evidence.json` from observed IDs and database
values. Do not hand-author a success value that is not backed by the candidate.

## Back up and restore the candidate

Configure the backup scripts for the candidate database and candidate asset
root. Write encrypted database and full-asset backups to the verified independent
destination, then validate both metadata files:

```bash
bash leadtrace/ops/backup/backup_postgres.sh
LEADTRACE_ASSET_BACKUP_MODE=full bash leadtrace/ops/backup/backup_assets.sh
python leadtrace/ops/backup/verify_backup.py \\
  /srv/leadtrace-backups/<candidate-database-id>/backup-metadata.json
python leadtrace/ops/backup/verify_backup.py \\
  /srv/leadtrace-backups/<candidate-assets-id>/backup-metadata.json
```

Restore those exact backups into another empty allowlisted database and another
empty asset root. Run `leadtrace/ops/restore/restore_drill.sh` against isolated
HTTP endpoints. Require a schema-v2 `PASS` report, exact Paper-centric counts,
zero integrity defects, verified Source and managed-asset hashes, matching
submission/publication hashes, and an RTO within the configured target.

## Preflight the staged candidate

Copy `leadtrace/ops/cutover/preflight.example.json` into a protected operations
directory and replace every placeholder with observed candidate evidence. Bind
`application_commit` to the exact tested commit. Point
`visual_acceptance_report`, both backup metadata paths, the restore report,
candidate and restore expected aggregates, the fixed Pilot Manifest, and the
acceptance evidence at their immutable files.

Set `base_url` to the loopback TLS candidate listener and
`old_dashboard_url` to `http://127.0.0.1:8765`. Export the candidate database URL,
candidate Redis URL, exact application commit, and protected role credentials,
then run:

```bash
LEADTRACE_DATABASE_URL="$LEADTRACE_CANDIDATE_DATABASE_URL" \\
LEADTRACE_APPLICATION_COMMIT='<exact selected commit>' \\
  .venv/bin/python leadtrace/ops/cutover/preflight.py \\
  --config /srv/leadtrace/acceptance/preflight.json \\
  --report /srv/leadtrace/acceptance/preflight-report.json
```

Proceed only when the command exits `0` and all eight checks pass. Independently
hash and archive the preflight report. A preflight run against the legacy/live
database is invalid evidence.

## Enter the approved maintenance window

Obtain the recorded Admin approval for the exact commit, candidate database,
backup IDs, restore report, preflight report hash, and route-switch time. Enter
maintenance on the currently routed service and verify Reviewer writes are
blocked while permitted reads still work.

Take fresh encrypted rollback backups of the currently routed database and
assets to the independent backup destination. Verify them before continuing.
These backups represent rollback state only; they do not replace the candidate
backup and restore evidence.

Recheck that candidate processes still use the candidate database, asset root,
and Redis namespace. Recheck `:8876` and `:8765` process identities. Do not run
Alembic or any import command during this window.

## Switch the primary route

Keep a copy of the loaded primary proxy file outside the included
`conf.d/*.conf` set. Install the candidate native configuration, validate it,
and reload only after validation succeeds:

```bash
sudo cp -p /etc/nginx/conf.d/leadtrace.conf /etc/nginx/leadtrace.conf.previous
sudo install -m 0644 leadtrace/deploy/nginx/nginx.native.conf \\
  /etc/nginx/conf.d/leadtrace.conf
sudo nginx -t
sudo nginx -s reload
```

The active route must now target the already-preflighted candidate processes;
there is no database migration at route-switch time.

Run the Paper-centric smoke test from a representative LAN client:

```bash
.venv/bin/python leadtrace/ops/cutover/smoke_test.py \\
  --config /srv/leadtrace/acceptance/smoke.json \\
  --report /srv/leadtrace/acceptance/smoke-after-cutover.json
```

Verify health, published Paper list/detail, authorized PDF range reads, draft
isolation, Admin catalog/submission access, the audit chain, and read-only
`/legacy-dashboard/`. Record the report hash.

## Exercise fallback before enabling writes

Follow `leadtrace/ops/runbooks/rollback-cutover.md` to route the primary endpoint
to the read-only old Dashboard. Confirm GET succeeds and write methods are
denied. This is a route-only exercise: preserve both databases, candidate assets,
audit history, submissions, and published versions.

Restore the candidate route, validate the proxy, reload, and run a second smoke
test into a new report. Remove the loopback preflight listener only after this
second test passes.

## Complete or stop

After both smoke tests and role-based UAT pass, obtain final Admin confirmation,
disable maintenance with a recorded reason, and monitor errors, queue depth,
Redis health, audit verification, and backup jobs through the stabilization
window. Keep `/legacy-dashboard/` read-only.

If any gate fails, keep Reviewer writes disabled, restore the previous route,
and follow `leadtrace/ops/runbooks/rollback-cutover.md`. Do not migrate the legacy
database, delete the candidate, or overwrite either backup set while the failure
is investigated.
