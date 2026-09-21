# LeadTrace

LeadTrace is a LAN-hosted, paper-centric review system for medicinal-chemistry
lead-optimization data. It runs beside the separate read-only legacy Dashboard;
the Dashboard remains available on port `8765` and is not part of this
application.

## Current workflow

The PostgreSQL schema treats one Paper as the scientific ownership boundary:

- one protected source PDF is registered as an Asset and Paper Source;
- one Paper stores the deterministic catalog fields extracted from that PDF;
- one active Reviewer assignment owns one editable Paper Workspace;
- the Workspace uses one fixed template, while the number of Compounds,
  Structures, Lineages, Edges, Evidence records, and Activities may vary;
- each Compound has at most one Structure, plus zero or more source-PDF image
  occurrences used to verify connectivity and identity;
- Evidence primarily supports Lineage Edges;
- every Reviewer mutation increments the Workspace version and appends history;
- submission freezes an immutable snapshot;
- an Admin must request changes or approve the frozen submission; and
- approval publishes an immutable Paper Version visible from the Paper library.

AI prefill is optional. It writes through the same scientific service boundary
as the Reviewer UI, but only into a blank untouched Workspace. The complete AI
payload is applied in one PostgreSQL transaction, never overwrites human work,
and creates the same single Structure row that a Reviewer may later edit in
place. The first adapter reads existing pilot artifacts; a future PDF model can
implement the same versioned payload contract.

PostgreSQL is the only business-data authority. Redis is delivery state for
Celery and may be rebuilt from PostgreSQL-backed jobs and extraction runs.

## Supervised AI Prefill

For a new or resumed Codex/DeepSeek prefill task, start with
[AI Prefill START_HERE](../docs/ai-prefill/START_HERE.md). It describes source-reader
separation, per-paper stages, delivery self-check, independent audit, Preview
operations and the persistent handoff. Code/docs are tracked; paper-run artifacts
and local Preview state remain in ignored `leadtrace-data/`.

## Local verification

Backend tests require an isolated PostgreSQL database whose name ends in
`_test`. The fixture rebuilds the shared `public` schema, so database-backed
pytest invocations must run serially.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e 'leadtrace/backend[test]'
cd leadtrace/backend
LEADTRACE_TEST_DATABASE_URL='postgresql+psycopg://leadtrace@127.0.0.1/leadtrace_test' \
  ../../.venv/bin/python -m pytest -v
```

Frontend verification:

```bash
cd leadtrace/frontend
npm ci
npm test -- --run
npm run typecheck
npm run build
npx playwright test
```

Static and migration checks:

```bash
cd leadtrace/backend
../../.venv/bin/python -m compileall -q app
../../.venv/bin/python -m alembic -c alembic.ini upgrade head --sql \
  >/tmp/leadtrace-migration.sql
../../.venv/bin/python -m app.cli.audit verify
cd ../..
docker compose -f leadtrace/deploy/compose.yaml config -q
git diff --check
```

## Development stack

Copy `deploy/env/example.env` to a protected `.env` next to
`compose.yaml`, replace all placeholders, provision the internal-CA files as
`deploy/nginx/tls/leadtrace.crt` and `deploy/nginx/tls/leadtrace.key`, then run
from the repository root:

```bash
docker compose --env-file leadtrace/deploy/.env \
  -f leadtrace/deploy/compose.yaml config
docker compose --env-file leadtrace/deploy/.env \
  -f leadtrace/deploy/compose.yaml up -d --build
```

After trusting the internal CA, open `https://leadtrace.lan:8876/`. Nginx is
the only externally published service. PostgreSQL, Redis, FastAPI, Vite, and
the workers remain internal. Both Web and Worker mount `source_pdfs` read-only;
the Worker also mounts the selected legacy AI artifact root read-only.

The one-shot `migrate` service upgrades a fresh PostgreSQL volume before Web
and Worker start. The application never changes schemas during startup and
refuses to serve when the database is not at the expected Alembic head.

## New pilot database only

Do not run the paper-centric migrations directly against a live or historical
business database. Verify its timestamped backup, restore that backup into a
separate isolated database for rollback testing, then create a new empty pilot
database. Import only the selected 20 source PDFs into that new database.

Build a deterministic manifest without modifying the source directory:

```bash
python leadtrace/ops/pilot/build_manifest.py \
  --source-root /read-only/source_pdfs \
  --source-directory '<pilot-source-directory>' \
  --source-root-key source_pdfs \
  --journal 'Journal of Medicinal Chemistry' \
  --publication-year 2024 \
  --volume 67 \
  --issue 5 \
  --created-on 2026-09-17 \
  --output /protected/acceptance/pilot-manifest.json
```

Validate all 20 hashes and metadata before writing, then apply the exact same
manifest:

```bash
cd leadtrace/backend
python -m app.cli.import_pilot \
  --manifest /protected/acceptance/pilot-manifest.json \
  --source-root /read-only/source_pdfs \
  --dry-run
python -m app.cli.import_pilot \
  --manifest /protected/acceptance/pilot-manifest.json \
  --source-root /read-only/source_pdfs \
  --apply
```

Both commands must report `verified=20`. A repeated apply is allowed only as
an exact idempotent replay.

## Accounts and native development

Configure a dedicated development database and protected runtime secrets. The
source-root key must match the pilot manifest.

```bash
export LEADTRACE_DATABASE_URL='postgresql+psycopg://leadtrace@127.0.0.1/leadtrace_dev'
export LEADTRACE_SESSION_SECRET='replace-with-a-long-random-development-secret'
export LEADTRACE_DEFAULT_ACCOUNT_PASSWORD='replace-with-a-protected-local-default'
export LEADTRACE_ALLOWED_HOSTS='["127.0.0.1","localhost","leadtrace.lan"]'
export LEADTRACE_ASSET_ROOT='/absolute/path/to/leadtrace-data/assets'
export LEADTRACE_SOURCE_ROOTS='{"source_pdfs":"/absolute/path/to/source_pdfs"}'
export LEADTRACE_NGINX_INTERNAL_TRANSFER='false'
cd leadtrace/backend
../../.venv/bin/python -m alembic -c alembic.ini upgrade head
../../.venv/bin/python -m app.cli.users create admin \
  --display-name 'LeadTrace Admin' --role admin --bootstrap
../../.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8876 --no-proxy-headers
```

The CLI never accepts or prints the configured default password. `--bootstrap`
is limited to the first Admin in an empty user database; later account creation
requires an enabled Admin actor and appends a credential-free audit event.

Health endpoints:

- `GET /health/live` checks only that the API process is alive.
- `GET /health/ready` returns HTTP 503 until PostgreSQL and protected storage
  are available.

The complete pilot procedure and evidence checklist are in
`docs/acceptance/leadtrace-paper-centric-pilot.md`.
