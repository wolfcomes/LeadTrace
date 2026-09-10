# LeadTrace source baseline

This directory contains the read-only inventory used to detect accidental
changes to the scientific migration inputs. The inventory records each file's
workspace-relative path, byte size, nanosecond modification time, SHA-256
digest, and media category. It never modifies an input file and refuses to
write a manifest inside an inventoried source root.

The production manifest currently covers `source_pdfs/`. Runtime caches,
virtual environments, logs, lock files, and temporary files are excluded. The
manifest is intentionally committed even though the inventoried source data is
not committed to Git.

## Build the baseline

Run from the repository root:

```bash
python leadtrace/ops/baseline/build_manifest.py \
  --workspace-root /data/home/zhangzhiyong/lead_optimization_collection \
  --output docs/baseline/2026-09-10-source-manifest.json
```

Use one or more `--source-root` arguments to inventory a narrower explicit
scope. Every source root must resolve inside `--workspace-root`.

## Verify the baseline

```bash
python -m leadtrace.ops.baseline.verify_manifest \
  docs/baseline/2026-09-10-source-manifest.json
```

A clean result is:

```text
changed=0 missing=0 unexpected=0
```

The verifier exits nonzero when a recorded file changed or disappeared, or
when an unexpected file appeared. Add `--json` for a machine-readable report.
Do not regenerate the committed baseline merely to hide a difference: first
determine whether the source change was authorized, reconcile scientific
counts, and review the exact affected paths.

## Fixed aggregate acceptance counts

`expected_aggregate.json` captures the approved migration counts and integrity
expectations. These values are checked from parsed CSV/JSON records; line-count
commands are not an acceptable substitute because quoted fields may contain
newlines.
