# LeadTrace Load Gate

Run the load gate only against an isolated acceptance environment populated
with representative data. The default shape uses a 4:1 Visitor/Reviewer weight;
25 users therefore model 20 concurrent readers and five concurrent editors.

Provide credentials and object IDs through the process environment. Do not put
them in shell history, repository files, Locust reports, or issue trackers:

```text
LEADTRACE_LOAD_VISITOR_USERNAME
LEADTRACE_LOAD_VISITOR_PASSWORD
LEADTRACE_LOAD_REVIEWER_USERNAME
LEADTRACE_LOAD_REVIEWER_PASSWORD
LEADTRACE_LOAD_PAPER_ID
LEADTRACE_LOAD_CHANGESET_ID
```

Example execution:

```bash
locust -f leadtrace/tests/load/locustfile.py \
  --host https://leadtrace-acceptance.lan:8876 \
  --headless -u 25 -r 5 -t 5m --csv load-results
```

The process exits non-zero when a named p95 target is missed, a required
scenario has no samples, or the aggregate failure rate exceeds one percent.
Run a separate cold-browser trace for "PDF first visible content < 2 s" and a
single RDKit structure preview for "normally < 2 s"; browser rendering time is
not represented accurately by an HTTP-only Locust client.

During a second five-minute acceptance run, restart Redis once and then one
worker process. PostgreSQL-backed jobs must reconcile without duplicate assets
or releases. Record request statistics, restart timestamps, reconciler output,
and post-run integrity validation. Component restarts are deliberate operator
actions and are not initiated by the load script.
