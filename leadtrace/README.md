# LeadTrace

LeadTrace is a LAN-hosted evidence and review platform for medicinal-chemistry
lead-optimization data. The new modular monolith is being introduced beside the
existing read-only Dashboard so the scientific corpus remains available during
migration.

This scaffold provides:

- a FastAPI process with independent liveness and dependency readiness checks;
- typed configuration that rejects unsafe production values;
- a Vue 3 and TypeScript application shell with explicit loading, ready,
  unavailable, forbidden, not-found, and error states;
- PostgreSQL with versioned Alembic migrations, Redis, a Celery worker, the
  frontend development server, and Nginx in Docker Compose;
- Admin-created local accounts with role-aware server sessions; and
- one externally published development port (`8876` by default). PostgreSQL,
  Redis, FastAPI, and Vite remain Docker-internal.

Business data pages, review workflows, and source migration are added in
subsequent implementation tasks.

## Local backend tests

```bash
python -m venv .venv
.venv/bin/python -m pip install -e 'leadtrace/backend[test]'
cd leadtrace/backend
../../.venv/bin/python -m pytest
```

## Frontend tests and build

```bash
cd leadtrace/frontend
npm ci
npm test
npm run build
```

## Development stack

Copy `deploy/env/example.env` to a private `.env` next to `compose.yaml`, replace
the placeholders, provision the internal-CA certificate and private key as
`deploy/nginx/tls/leadtrace.crt` and `deploy/nginx/tls/leadtrace.key`, and run
from the repository root:

```bash
docker compose --env-file leadtrace/deploy/.env \
  -f leadtrace/deploy/compose.yaml config
docker compose --env-file leadtrace/deploy/.env \
  -f leadtrace/deploy/compose.yaml up -d --build
```

Without `--env-file`, Compose uses explicitly development-only defaults. After
the internal CA is trusted by the client and the certificate SAN includes
`leadtrace.lan`, open `https://leadtrace.lan:8876/`. The Compose Nginx service
always expects TLS; its port must not be documented or operated as plain HTTP.
The legacy Dashboard remains separate on port 8765.

The one-shot `migrate` service upgrades a fresh PostgreSQL volume before the
web process and worker start. The application itself never changes schemas at
startup; it refuses to serve when the database is not at the expected Alembic
head.

## Reviewer scientific workspace rollout

Migration `0018_reviewer_scientific_workspace` adds immutable OCSR proposal
evidence, source Regions, Paper review scopes, and append-only attestations.
Baseline imports created after this migration include proposal/crop evidence in
the candidate and its first Release. A baseline that was published before the
proposal tables were populated must be repaired explicitly by an enabled Admin;
historical Release manifests and active Reviewer changesets are never edited or
silently rebased.

After reauthenticating as an Admin, run the evidence-only successor operation
with the exact source fingerprint recorded in the current Release's baseline
metadata:

```bash
python -m app.cli.import_proposals \
  --source-root /absolute/path/to/source-workspace/source_pdfs/project \
  --source-manifest /absolute/path/to/source-manifest.json \
  --expected-aggregate /absolute/path/to/expected-aggregate.json \
  --source-fingerprint <64-character-baseline-fingerprint> \
  --actor-id <admin-uuid> \
  --idempotency-key machine-evidence-2026-09-15
```

The command prints only Release IDs, counts, and idempotency state. It never
prints credentials, storage keys, source paths, or crop paths. The successor
Release keeps the existing `human_review` metric and remains unverified until a
Reviewer Paper attestation, independent Admin approval, and successor Release
publication complete the normal workflow. Verify the metric before publishing:

```bash
python -m app.cli.audit verify
```

## Native development without Docker

Docker is optional during the current development phase. Point LeadTrace at a
dedicated PostgreSQL database whose name ends in `_test` for tests, or at a
dedicated development database for manual use. Do not use a production or
scientific source-data database.

This native Uvicorn command is a direct HTTP development mode without Nginx.
It is not accepted for production cutover or LAN TLS validation.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e 'leadtrace/backend[test]'
export LEADTRACE_DATABASE_URL='postgresql+psycopg://leadtrace@127.0.0.1/leadtrace_dev'
export LEADTRACE_SESSION_SECRET='replace-with-a-long-random-development-secret'
export LEADTRACE_DEFAULT_ACCOUNT_PASSWORD='replace-with-a-protected-local-default'
export LEADTRACE_ALLOWED_HOSTS='["127.0.0.1","localhost","leadtrace.lan"]'
export LEADTRACE_ASSET_ROOT='/absolute/path/to/leadtrace-data/assets'
export LEADTRACE_SOURCE_ROOTS='{"baseline":"/absolute/path/to/source-workspace"}'
export LEADTRACE_BASELINE_IMPORT_ROOT='/absolute/path/to/source-workspace/source_pdfs/project'
export LEADTRACE_BASELINE_SOURCE_MANIFEST='/absolute/path/to/source-manifest.json'
export LEADTRACE_BASELINE_EXPECTED_AGGREGATE='/absolute/path/to/expected-aggregate.json'
export LEADTRACE_NGINX_INTERNAL_TRANSFER='false'
cd leadtrace/backend
../../.venv/bin/python -m alembic -c alembic.ini upgrade head
../../.venv/bin/python -m app.cli.users create admin \
  --display-name 'LeadTrace Admin' --role admin --bootstrap
../../.venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8876 --no-proxy-headers
```

`LEADTRACE_SOURCE_ROOTS.baseline` is the manifest workspace used to resolve
protected source assets. `LEADTRACE_BASELINE_IMPORT_ROOT` is the narrower,
read-only dataset directory containing `01_manifest` and `09_paper_review`.
The two other baseline settings point to the approved manifest and aggregate
contract. The Admin HTTP backfill operation is unavailable unless all three
paths are configured and mounted read-only in the web container.

Replace the default-password placeholder through a protected, non-versioned
service environment before creating accounts. The CLI never accepts or prints
the value. `--bootstrap` is limited to the first Admin in an empty user
database; later CLI account creation and individual reset require an explicit
enabled Admin `--actor-id` and append a credential-free audit event. Browser
password changes are optional after login and are available from the signed-in
account area.
In native direct mode, proxy headers stay disabled so a LAN client cannot
forge the source address used by login throttling.

Health endpoints:

- `GET /health/live` confirms only that the API process is alive;
- `GET /health/ready` returns HTTP 503 until PostgreSQL and the protected asset
  root are available.
