# LeadTrace Cutover Rollback Runbook

## When to use this procedure

Use a route fallback when the new primary route, role permissions, current
release, assets, audit chain, database, Redis, or Celery worker fails a cutover
gate. Keep maintenance active for Reviewer writes and preserve all new revisions,
changesets, release manifests, audit events, and assets.

A route fallback is not a database restore. Do not restore production data,
delete revisions, or move a release pointer merely because the new web route
is unhealthy. A scientific release problem uses the Admin release rollback;
a database restore requires a separate incident decision and a verified
isolated restore candidate.

## Return the old Dashboard to the primary route

Confirm the old Dashboard answers on `127.0.0.1:8765`. Keep the previously
loaded Nginx file at `/etc/nginx/leadtrace.conf.previous`. Install the committed
read-only fallback, validate it, and only then reload:

```bash
sudo install -m 0644 leadtrace/deploy/nginx/nginx.native-fallback.conf \
  /etc/nginx/conf.d/leadtrace.conf
sudo nginx -t
sudo nginx -s reload
```

From a LAN client, verify a GET to `/` returns the old Dashboard and POST, PUT,
PATCH, and DELETE are denied. Record the trigger, operator, timestamp, current
LeadTrace release key, last successful smoke report, and Nginx validation
output. Do not expose internal PostgreSQL, Redis, FastAPI, or old Dashboard
ports to make fallback work.

## Diagnose without destroying evidence

Keep the LeadTrace web, worker, database, assets, and logs available on their
internal interfaces when safe. Verify the current release and audit chain,
capture request IDs, and compare the last successful preflight and backup IDs.
Do not copy passwords, tokens, cookies, database URLs, or storage paths into
the incident record.

For a bad published release, use the Admin rollback workflow to create an
audited release transition to an existing validated release. Never edit the
release row directly. Run release and asset validation before changing the
route back.

## Restore LeadTrace to the primary route

After the cause is corrected, install the native LeadTrace configuration,
validate it, and reload:

```bash
sudo install -m 0644 leadtrace/deploy/nginx/nginx.native.conf \
  /etc/nginx/conf.d/leadtrace.conf
sudo nginx -t
sudo nginx -s reload
```

Run a fresh preflight when database, release, asset, backup, or source state
changed. Always run a new post-route smoke report:

```bash
.venv/bin/python leadtrace/ops/cutover/smoke_test.py \
  --config /srv/leadtrace/acceptance/smoke.json \
  --report /srv/leadtrace/acceptance/smoke-after-return.json
```

Confirm Visitor, Reviewer, and Admin behavior, the target release, authorized
PDF access, audit verification, and `/legacy-dashboard/` read-only access.
Disable maintenance only after Admin approval. Link the fallback and recovery
reports in the acceptance record.
