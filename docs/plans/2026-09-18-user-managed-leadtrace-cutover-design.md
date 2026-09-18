# User-Managed LeadTrace Cutover Design

**Status:** Approved for implementation planning

**Date:** 2026-09-18 (Asia/Shanghai)

## Goal

Deploy the paper-centric LeadTrace Pilot as a usable LAN service without
server-administrator privileges, while preserving the legacy database,
Dashboard, Source PDFs, encrypted backups, restore evidence, and an immediate
route-only rollback path.

The service will be reachable by a small number of controlled LAN clients at
`https://10.21.53.251:8876`. Those clients will receive and trust a user-owned
Caddy local-CA root certificate through a short, read-only onboarding flow.

## Constraints and non-goals

- No `sudo`, root shell, `/etc` writes, Docker socket access, or system-service
  changes are assumed.
- The current legacy route, old Dashboard on `127.0.0.1:8765`, and legacy
  database remain intact until the new route has passed all smoke tests.
- Alembic is never run against the current legacy database.
- `source_pdfs/` remains read-only and is never copied back into or rewritten by
  the application.
- The organization does not currently provide a LAN certificate for
  `10.21.53.251`; the user-owned Caddy internal CA is therefore the selected
  trust model.
- This design does not create public DNS, request a publicly trusted
  certificate, or make the application accessible from the public Internet.
- The existing AI extraction protocol, Skill document, and evaluation standard
  remain deferred.

## Architecture

All durable candidate state lives below the user-owned project data root:

```text
leadtrace-data/production/
├── postgres/                 # PostgreSQL 16 data directory and socket
├── redis/                    # Redis append-only data and configuration
├── assets/                   # managed assets restored from the verified backup
├── caddy/                    # Caddy config, local CA state, access logs
├── client-trust/             # public root.crt, fingerprint, install guide
├── backups/                  # cutover and rollback backup metadata/payloads
├── run/                      # lock, PID, and readiness state
└── logs/                     # user-owned service logs
```

The user-level processes are:

| Component | Binding / identity | Role |
|---|---|---|
| PostgreSQL 16 | loopback high port, new production database name | durable application database |
| Redis 7 | loopback high port, dedicated namespace/data root | Celery broker and result backend |
| LeadTrace Web | loopback high port | paper-centric API |
| Celery Worker | no LAN binding | crop and AI-prefill jobs |
| Caddy | `10.21.53.251:8876` HTTPS | LAN TLS edge, static frontend, API proxy |
| Legacy Web | existing loopback `:8000` | rollback target, unchanged during stabilization |
| Legacy Dashboard | existing loopback `:8765` | read-only fallback, unchanged |

The candidate production database is restored from the already verified
`cutover-candidate-20260918-database` backup into a new durable database, for
example `leadtrace_production_20260918`. It is not the temporary PostgreSQL
acceptance database currently used by the Pilot and it is not the legacy
`leadtrace_acceptance` database.

The managed asset tree is restored from the matching
`cutover-candidate-20260918-assets` backup. Its Source namespace contains only
the approved 20-Paper logical Source bundle; the physical `source_pdfs/` tree
remains an independent read-only input.

## User-level service lifecycle

The deployment uses a single idempotent user-owned supervisor script and
per-component wrappers. The script:

1. acquires a user-owned `flock` lock;
2. verifies that every configured data directory is below the production root;
3. starts PostgreSQL and waits for the new database to accept connections;
4. starts Redis with the dedicated configuration and verifies `PING`;
5. starts Web and Celery with the production database, Redis namespace, asset
   root, Source root, and exact application commit;
6. validates the candidate Caddy configuration before binding `:8876`; and
7. runs health and worker readiness checks before reporting success.

The current user crontab receives one `@reboot` entry pointing to this
supervisor. It is intentionally not a systemd unit and does not require
`loginctl enable-linger`. Manual start, stop, restart, and status commands use
the same script, so reboot recovery and operator recovery share the same code
path. Duplicate starts are refused by PID/lock checks.

The old Caddy configuration and process identity are recorded before the route
switch. During stabilization the old Web, old Dashboard, and their database
remain running; they are not silently replaced by the new services.

## LAN TLS and client certificate onboarding

Caddy uses its user-owned internal PKI and issues a certificate containing the
IP SAN `10.21.53.251`. The CA state and private key remain below the user-owned
`production/caddy/` directory with restrictive permissions. Only the public
root certificate is distributed to clients.

To keep onboarding simple for a small number of controlled clients, the
deployment creates:

- `client-trust/leadtrace-root.crt`;
- `client-trust/leadtrace-root.sha256`;
- a short OS-specific import guide; and
- a temporary, read-only certificate-only bootstrap endpoint on a separate high
  port, such as `http://10.21.53.251:8875/leadtrace-root.crt`.

The bootstrap endpoint serves no API, HTML application, credentials, cookies, or
database content. A client downloads the public certificate, compares its SHA
256 fingerprint with the value supplied by the operator, and imports it into
the client's trust store. After all controlled clients are onboarded, the
bootstrap endpoint is disabled and the port is released. The normal application
route remains HTTPS on `:8876` throughout.

The root certificate is not secret, but the fingerprint comparison prevents a
client from silently trusting a substituted certificate during HTTP bootstrap.
The private CA key is never copied to any client and is never checked into Git.

Client verification after import is:

```bash
curl --fail --cacert leadtrace-root.crt \
  https://10.21.53.251:8876/health/ready
```

The client guide will include the equivalent trust-store steps for the few
managed Linux, macOS, and Windows clients. No client needs a hosts-file entry.

## Data and route cutover sequence

The implementation will execute these gates in order:

1. Create the persistent production root and user-owned service scripts.
2. Initialize a new PostgreSQL 16 cluster on persistent storage and create a
   new production database identity.
3. Restore the verified candidate database and managed assets into the new
   targets; do not restore into the legacy database.
4. Start the candidate Web, Worker, Redis, and a loopback-only Caddy preflight
   listener.
5. Run a fresh eight-gate preflight against the persistent targets, including
   exact 20-Paper counts, audit integrity, permissions, Source manifest, worker
   pong, HTTPS, and backup/restore evidence.
6. Generate the Caddy local CA certificate, client bundle, fingerprint, and
   temporary onboarding endpoint. Verify the certificate contains
   `10.21.53.251` and is not expired.
7. Build and validate the final user-owned Caddy route without loading it into
   the current `:8876` process yet.
8. Enter the approved maintenance interval, block Reviewer writes on the old
   route if the legacy service supports it, and take fresh encrypted rollback
   backups of the currently routed legacy state.
9. Stop only the old Caddy edge process, preserve its configuration, and start
   the new Caddy route on `10.21.53.251:8876`.
10. Run the post-cutover smoke test from the server and at least one controlled
    LAN client: health, Visitor, Reviewer, Admin, authorized PDF range reads,
    audit verification, and read-only legacy fallback.
11. Exercise route-only fallback by restoring the old Caddy configuration and
    verifying old Dashboard GET plus denied writes, then restore the new route
    and run a second smoke test.
12. Disable the temporary certificate bootstrap endpoint, obtain final Admin
    confirmation, and monitor the new route during stabilization.

There is no database migration or import at route-switch time. The switch only
changes the Caddy edge target to an already verified Web/Worker/database/asset
set.

## Rollback

If TLS, Web, Worker, database, asset, permission, audit, or smoke verification
fails, Reviewer writes remain disabled and the route is switched back to the
preserved old Caddy configuration. The rollback is a route-only operation:

- it does not delete the candidate database;
- it does not restore or rewrite the legacy database;
- it does not delete candidate assets or audit history; and
- it does not reverse the paper-centric Alembic boundary.

After the old route is healthy, the failure evidence, process identities,
backup IDs, and Caddy validation output are retained for diagnosis. A later
return to the candidate route requires a fresh preflight whenever database,
asset, backup, source, or release state changes.

## Verification and acceptance

Before the route switch, the following must be freshly verified:

- persistent PostgreSQL database identity is distinct from both the legacy and
  temporary acceptance databases;
- persistent asset root is writable by the user service and contains the
  restored verified set;
- Caddy certificate SAN includes `10.21.53.251` and the client root fingerprint
  matches the served certificate chain;
- all eight existing cutover preflight checks pass against the persistent
  targets;
- Web and Worker use the exact application commit and candidate database;
- `source_pdfs/` and the legacy Dashboard remain unchanged;
- old Caddy configuration is backed up and reload/rollback validation passes;
- at least one controlled LAN client can import the root certificate and run a
  successful HTTPS health check; and
- a user-level restart drill reproduces the complete process stack without
  administrator privileges.

Fresh evidence is written outside the repository under the protected
`leadtrace-data/production/` operations root. Repository documents contain no
passwords, database URLs, session secrets, cookies, private keys, or absolute
protected Source paths.

## Deferred follow-up

- Replace the user-owned internal CA with an organization-issued certificate if
  one becomes available.
- Add certificate renewal and client re-onboarding automation before the first
  internal CA certificate expires.
- Consider enabling user lingering or a formally managed service account if the
  host owner later grants that authority.
- Design the AI extraction protocol, Skill, and evaluation benchmark after the
  first real output review, as previously agreed.
