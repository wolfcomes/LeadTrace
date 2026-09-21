# LeadTrace repository instructions

## AI_prefill tasks

For requests to run, supervise, evaluate, improve, or resume AI_prefill (including
AI_prefilll / AI prefill), start with `docs/ai-prefill/START_HERE.md`. It is the
current operational entry point; historical verification reports are evidence,
not the current runbook. Read the latest run's `HANDOFF.md` before resuming.

- Codex supervises and reports; DeepSeek harness reads original paper text/images.
  Do not read source PDFs, extracted page text, original crops, or reasoning logs
  that contain source content unless the user explicitly changes this division.
  Candidate/reviewer outputs and file identity metadata may be inspected.
- Use `dsh --profile headless` for scientific extraction/review. Codex subagents
  are not substitutes for DeepSeek paper readers. Keep one candidate writer per
  paper/stage and separate fresh reviewer calls.
- Use current guides + rerun lessons + delivery self-check; copy the actual files
  into each new task bundle and hash them. Never rewrite a historical bundle.
- The producer must not access Preview credentials or apply data. Supervisor
  Preview operations follow `leadtrace/ops/runbooks/ai_prefill_preview.md` and the
  current local instance descriptor. An explicit request to view imperfect results
  in Preview authorizes draft display, not scientific approval.
- `leadtrace-data/` contains ignored runtime artifacts and local credentials.
  Never commit it, source corpus PDFs, database dumps, tokens, or rendered paper
  images. Record portable instructions in Git and live state in the run handoff.
- Existing workspaces may contain human edits. Never reset workspace versions,
  clear data to bypass the blank-workspace apply rule, or fabricate receipts.
- Preview scientific data, candidates, assets and database dumps must not be
  imported into the production database as part of merge or deployment. Production
  retains its own scientific records. A schema upgrade does not authorize data import.
- Keep one current version of each operational guide in the source tree. Fold
  accepted lessons into current guidance; archive completed experiment reports and
  superseded plans outside the tracked tree (with hashes) before integration.
  Preserve historical Git commits and frozen run bundles; retain required schema
  versions, database migrations and regression tests.
- User scope/authorization takes precedence. Preserve the ai-prefill-tools
  worktree after integration; it hosts the current local Preview and is retained
  for future improvements. Do not remove it as routine branch cleanup.

## Verification and integration

Database tests require a separate disposable PostgreSQL cluster and an explicit
`LEADTRACE_TEST_DATABASE_URL` ending in `_test`; tests reset the public schema.
Never use the live Preview/production cluster as the test target. Run backend
DB suites serially. Frontend tests may run alongside them.

Read `leadtrace/README.md` for development checks. Merging source changes does
not authorize production migration/deployment. Preserve current main's auth,
Ketcher and CSP fixes when integrating AI_prefill changes.
