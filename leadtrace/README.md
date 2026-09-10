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
- PostgreSQL, Redis, Celery worker, frontend development server, and Nginx in
  Docker Compose; and
- one externally published development port (`8876` by default). PostgreSQL,
  Redis, FastAPI, and Vite remain Docker-internal.

Business data pages, user accounts, review workflows, and migrations are added
in subsequent implementation tasks.

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

Health endpoints:

- `GET /health/live` confirms only that the API process is alive;
- `GET /health/ready` returns HTTP 503 until PostgreSQL and the protected asset
  root are available.
