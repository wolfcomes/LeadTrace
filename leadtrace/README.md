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
the placeholders, and run from the repository root:

```bash
docker compose --env-file leadtrace/deploy/.env \
  -f leadtrace/deploy/compose.yaml config
docker compose --env-file leadtrace/deploy/.env \
  -f leadtrace/deploy/compose.yaml up -d --build
```

Without `--env-file`, Compose uses explicitly development-only defaults. Open
`http://127.0.0.1:8876/`. Formal LAN rollout will add an internal-CA TLS
certificate and choose the final fixed port without disturbing the legacy
Dashboard on port 8765.

The one-shot `migrate` service upgrades a fresh PostgreSQL volume before the
web process and worker start. The application itself never changes schemas at
startup; it refuses to serve when the database is not at the expected Alembic
head.

## Native development without Docker

Docker is optional during the current development phase. Point LeadTrace at a
dedicated PostgreSQL database whose name ends in `_test` for tests, or at a
dedicated development database for manual use. Do not use a production or
scientific source-data database.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e 'leadtrace/backend[test]'
export LEADTRACE_DATABASE_URL='postgresql+psycopg://leadtrace@127.0.0.1/leadtrace_dev'
export LEADTRACE_SESSION_SECRET='replace-with-a-long-random-development-secret'
export LEADTRACE_ALLOWED_HOSTS='["127.0.0.1","localhost","leadtrace.lan"]'
export LEADTRACE_ASSET_ROOT='/absolute/path/to/leadtrace-data/assets'
cd leadtrace/backend
../../.venv/bin/python -m alembic -c alembic.ini upgrade head
../../.venv/bin/python -m app.cli.users create admin \
  --display-name 'LeadTrace Admin' --role admin
../../.venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8876 --no-proxy-headers
```

The Admin CLI prompts twice for the one-time password. It also supports an
owner-only (`0600`) `--password-file`; plaintext password arguments are not
accepted. The first browser login must change the one-time password before any
administrative action is allowed.
In native direct mode, proxy headers stay disabled so a LAN client cannot
forge the source address used by login throttling.

Health endpoints:

- `GET /health/live` confirms only that the API process is alive;
- `GET /health/ready` returns HTTP 503 until PostgreSQL and the protected asset
  root are available.
