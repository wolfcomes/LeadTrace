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

Compound, Activity and LineageEdge records may carry one optional review hint.
The same ⚠ disclosure shows its explanation in draft, submission and published
views. Reviewers resolve it through existing edits and explicitly clear the text;
confirming a record does not silently remove a hint. Prefill still requires a
complete source-supported structure, including a reasonable reconstruction.

AI prefill is optional. It writes through the same scientific service boundary
as the Reviewer UI, but only into a blank untouched Workspace. The complete AI
payload is applied in one PostgreSQL transaction, never overwrites human work,
and creates the same single Structure row that a Reviewer may later edit in
place. The first adapter reads existing pilot artifacts; a future PDF model can
implement the same versioned payload contract.

PostgreSQL is the only business-data authority. Redis is delivery state for
Celery and may be rebuilt from PostgreSQL-backed jobs and extraction runs.

## Admin submission review

The approval page uses Reviewer-style, read-only article, Compound and Lineage
records with the comparison baseline on the left and the frozen submission on the
right. The default directory lists changed records; all records remain available.
A selected Compound keeps its structure, activities and supporting evidence in
context. Only changed fields and measurements expand by default. Unchanged sections and
fields stay collapsed, including unchanged chemistry after a status edit and
unchanged measurements after an evidence edit. Issue badges remain visible.
Changed sections and activities sort before unchanged content in the same order
on both sides. Matching disclosures expand together on both sides. Original evidence
crops are collapsed and loaded only when expanded, using verified frozen PDF
identity and coordinates. Larger region/page views are available on demand.

Each affected Lineage is reviewed as a whole: paired graphs use shared node
positions and viewport coordinates, with linked selection, optional synchronized
pan/zoom, change navigation and an expanded comparison view. The graph uses compact
labelled nodes and arrows. Edge text shows only a short change marker near that
Edge's arrow; unchanged Edges have no text. Relationship types remain in the
selected Edge's details rather than repeating across overlapping branches.
Lineage approval includes node additions/removals,
Edge changes (including endpoint changes and supporting evidence), and direct
Lineage metadata changes. Compound identity, structure, activity, highlights and
Compound-only evidence edits remain in the Compound review and do not mark nodes
or Lineages changed. Evidence actually used by an Edge still belongs in its
Lineage comparison, including evidence shared with a Compound. Node selection
shows only membership before/after; Edge details show endpoint labels, relationship
fields and evidence, without embedded Compound cards. Membership role/order-only
edits remain in complete history. Viewing never writes a graph layout or changes
the Reviewer workspace.

Net changes compare with the previous frozen submission, or the reliably
reconstructed state before the first Reviewer edit. Missing or unsupported history
shows an explicit comparison warning. Routine confirmations are collapsed;
unresolved issue resolutions, cleared hints, deletions and evidence reassignments
remain visible. Complete frozen content and all actors' history expand on demand.
Approval still applies to the entire frozen submission and its content hash.

Admin navigation lists genuine Reviewer submissions only, with their original
submitter, time, note and decision. The directory offers pending and all-submission
views, including returned and approved articles. Historical versions are read-only;
only the latest pending Reviewer snapshot/hash is actionable. Real return decisions
on later technical snapshots remain visible as follow-up context with their original
identity and reason, rather than being confused with automatic supplement closures.

Explicit metadata-supplement links are verified against identities, frozen hashes,
history boundaries and unchanged non-metadata science. Supplements appear in a
separate, initially collapsed comparison and do not inflate Reviewer change counts.
Later Reviewer rounds reference the preceding real Reviewer submission. Verified
metadata supplements form the human-edit baseline for affected fields, so subsequent
human corrections remain visible. The UI identifies this baseline, and the original
preceding snapshot remains accessible through navigation. Missing or invalid history
produces warnings and read-only directory entries, never fabricated versions.

Post-submission additions require Reviewer checking and resubmission; technical
supplement snapshots cannot be approved. Return them through the existing audited
workflow, retaining all draft content, scientific viewing receipts, human notes and
unchanged confirmations. See the article metadata supplement runbook.

Admin clients opt in with `reviewer_rounds=true` on list and detail requests.
`include_comparison=true` without that option retains the earlier comparison API;
the default responses preserve their legacy shape. These are display projections,
not changes to immutable submissions or historical actors.

## Interface language

The page-top language selector switches between the existing Chinese interface
and English, including the login page. The browser remembers the choice; switching
preserves unsaved editor state. Scientific records, source quotations and user
text remain in their original language. UI messages live in `frontend/src/i18n/`.

## AI Prefill and self-check

For a new or resumed AI prefill task, start with
[AI Prefill START_HERE](../docs/ai-prefill/START_HERE.md). It describes source-reader
separation, model-led routine and supervised evaluation modes, prefill/repair/review
task entries, delivery self-check, independent audit, Preview
operations and the persistent handoff. Code/docs are tracked; paper-run artifacts
and local Preview state remain in ignored `leadtrace-data/`.

## Article research metadata

Article information includes PMID/PMCID with identifier provenance; original
Abstract, source locator, check state and missing/review notes; and source-backed
research profiles. Molecule types retain the compatible `modalities` key and use two fixed multi-select groups in one card: primary types (small-molecule inhibitor, agonist, antagonist, inverse agonist, activator, modulator with unresolved detail, PROTAC, molecular glue, other, unresolved) and supplementary features (allosteric modulation, covalent action, macrocyclic, peptide/peptidomimetic, prodrug). Classifications describe the optimized series, with independent source evidence, and never automatically reinterpret old broad labels. Mechanisms, diseases and optimization goals allow
multiple entries. Molecular forms is retired from new extraction and ordinary UI;
historical payloads remain compatible. Abstract provenance stays in internal details,
while ordinary reading shows the original abstract and actionable issues only. Targets distinguish primary/co-primary,
selectivity, off-target, mechanistic, biomarker and unknown roles; species and gene
accessions remain optional and must not be inferred from a name alone. Each profile
entry has its own source and optional review hint. Empty fields do not establish
absence in the source. Article labels summarize the research; Compound properties,
measurements and Lineage data remain in their existing records.

Reviewer article reading uses six modules in two desktop columns with fixed headers and independently scrolling bodies; mobile reading uses one column. Original evidence quotations and source/page locators expand on demand. Optional crops load only when opened and use verified frozen PDF identity. Admin comparisons align corresponding entries and synchronize scrolling, with changed evidence expanded and unchanged content folded. Evidence supplements preserve existing metadata and immutable submission history while leaving replacement submissions pending approval.

Reviewer edits use workspace version checks and audited updates. Frozen submission
and publication snapshots preserve the metadata, and Admin compares changed groups
before folded unchanged groups. Old candidates/snapshots omit new default fields
for compatibility. New backend deployments require additive migration0035.
AI generation explicitly checks Abstract and records text/source or a reason for
absence; deterministic checks report gaps without inventing content or blocking
otherwise reviewable legacy drafts. Scientific approval still belongs to humans.

Authorized metadata batches can fill existing drafts through the version/hash
checked operator in [the metadata supplement runbook](ops/runbooks/article_metadata_supplement.md).
It preserves populated human fields, assignment and scientific viewing receipts;
AI additions are shown separately from human changes using audited field/group
deltas. Explicit supplemental revisions retain the published snapshot until a
new Reviewer submission is approved. This path needs no schema migration.

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

## Reviewer workbench

Reviewers can switch a Lineage between Graph, Compound and Edge views. Graph Add
Node selects a Compound already registered in the same paper. Graph Add Edge
selects endpoints before opening the existing relation form. Node positions and
edge curves have separate versions for point and structure modes; Save layout
persists presentation without changing scientific workspace versions.

Article information supports a source abstract and structured PDB mentions.
Metadata uses ordinary workspace version checks and is frozen on submission.
Optional new AI bibliography fields preserve the serialized shape of older inputs.

Viewing progress records only Compound and Lineage groups. Compound signatures
include structures, source images, activities and linked evidence; Lineage
signatures include member Compound content, edges and linked evidence. Changes
invalidate related groups, while layouts and unrelated groups remain independent.
Only these two groups have viewed badges/counts. Child scientific dispositions and
review hints remain explicit human decisions. Group coverage satisfies related
section reading requirements; bibliography keeps manual section confirmation and
unassigned Evidence remains covered by the final whole-paper confirmation.
Historical narrow-scope receipts are retained but never promoted to group viewing.
The final human submission confirmation and server scientific checks remain
mandatory. Existing manual section dispositions are preserved. Once group tracking
starts, its current assignee must view all current groups before submission.

The Chinese and English reviewer guides and group-abbreviation reference use one
source, `frontend/src/review/help/reviewer-guide.json`, exposed in the workbench.
Illustrated beginner handbooks: [中文 HTML](frontend/public/reviewer-guide/zh.html) and
[English HTML](frontend/public/reviewer-guide/en.html), linked from workbench help.
The same bilingual source generates portable [中文 Markdown](../docs/reviewer/reviewer-guide.zh.md)
and [English Markdown](../docs/reviewer/reviewer-guide.en.md). Screenshot provenance,
offline distribution and maintenance: [Reviewer documentation](../docs/reviewer/README.md). Regenerate with
`python leadtrace/ops/reviewer/render_guide.py`; CI/local check uses `--check`.

Article information also supports evidence-backed Compound highlights: study
starting points, hub compounds (`optimization_start`), and paper-prioritized compounds. These are independent of local
Lineage topology. Multiple roles/scopes are supported, with explicit draft,
reviewer-confirmed or unresolved dispositions. Viewing does not confirm a role;
editing an assertion requires a new disposition. Annotation changes invalidate
related Compound/Lineage viewing signatures. Draft annotations block submission.
The hub-compound label is added through Article information → Add article annotation, with scope, rationale and Evidence; it appears on Compound cards and Lineage nodes without changing local roles or splitting graphs. Deployments require additive migration `0036_optimization_start`, which expands only the highlight role constraint and does not backfill scientific assertions.
Highlights are versioned, frozen, projected on publication and exported with
separate review metadata; AI apply always creates drafts. Legacy candidates and
snapshots without highlights retain their serialized shape. Empty means
unrecorded, not a scientific claim that no compound was prioritized.

## Admin AI task console

The article management page supports recall, verified archive/restart, first generation
with bounded producer self-check, fresh-context review with a repair proposal in the same model invocation, then explicit acceptance of saved changes. Reports default to category totals, coverage and conservative review status statistics; full diagnostics and proposal differences expand on demand. Repair generation never changes the draft, and accepting a saved proposal applies a version-bound delta without calling a model. A persistent
queue defaults to four concurrent tasks globally and one open task per paper.
[Admin operations and configuration](../docs/ai-prefill/admin-console.md) describe
model presets, independent review coverage, archives and restart recovery.
