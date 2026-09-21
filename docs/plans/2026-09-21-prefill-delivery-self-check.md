# DeepSeek delivery self-check implementation plan

**Goal:** User-authorized Preview refresh of 007/009/020, followed by an executable producer self-check and clear source-review instructions.

**Architecture:** Keep Preview application and scientific approval separate. Refresh only the untouched three workspaces using existing versioned domain services with before/after snapshots in per-paper transactions. Keep experimental candidates immutable. Add an offline `candidate self-check` command which composes existing validation/coverage with deterministic semantic checks and optionally validates a strict source self-review sidecar. No database/Preview access by the producer; no automatic candidate repair or approval.

**Alternatives considered:** Documents alone are easy but were not reliably followed. Enforcing every rule in Preview immediately risks blocking intentional review of partial candidates. Recommended: offline checks + documented source recheck before delivery, preserving supervisor control of Preview.

**Scope authorized in conversation:** Apply current results to Preview; turn existing rules into checks and write producer self-check guidance. No production writes, schema migration, whole-paper source reading by Codex, new extraction run, or scientific repairs in this turn.

## Tasks

1. Preserve and apply three candidates through existing domain mutation services; check counts, draft states, assets and Reviewer HTTP access. Save refresh record rather than fabricating an initial-prefill receipt.
2. Add failing tests for new CLI path and semantic rules: missing inventory, dose vs dose-based endpoints, ratio units, legitimate thresholds and negative activity, duplicates, missing lineage type, stale self-review hash, incomplete/source-review statuses and nonexistent edge references.
3. Implement `assistance_self_check.py` and wire CLI action with `--inventory`, `--self-review`, `--output`. Report file hash and canonical hash distinctly. Exit4 for correction or incomplete self-review,0 only means ready for independent review,2 invalid input. Preserve existing validate/apply behavior.
4. Write self-check guide, strict JSON template and prompt/runbook entry points. Default one source self-check round, bounded two correction rounds; retain partial results and unresolved items. Never represent ND as0, no-data as omission, missing text as invalid SAR, or self-check as supervisor approval.
5. Run focused tests and read-only regression on frozen last-three candidates. Verify input hashes unchanged, actual issues found, and document unimplemented scientific/tuple audit automation.
