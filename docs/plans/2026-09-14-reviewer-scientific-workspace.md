# Reviewer Scientific Workspace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a typed Reviewer workspace for PDF Regions, molecule objects, OCSR proposals, and structures; expose crop/RDKit/source context; add the first-page molecule-object queue under existing review tasks; and make Paper-level attestation the authoritative human-verification gate.

**Architecture:** Keep one Paper ReviewTask, one changeset, and one successor-Release lifecycle. Add `MoleculeProposal` as a revisioned object, immutable Paper review scopes and append-only attestations, then expose one version-consistent workspace projection consumed by dense Vue components. Object dispositions drive queue/completeness state, while only an attested Paper revision and Admin-approved published Release drive public verification.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Alembic, Pydantic 2, RDKit, PyMuPDF, Vue 3, TypeScript, Zod, Pinia, Vite, Vitest, Vue Test Utils, Playwright.

---

## Preconditions and execution rules

- Work only in `.worktrees/reviewer-scientific-workspace` on branch
  `codex/reviewer-scientific-workspace`.
- The Dashboard-alignment work is already merged into the branch base at
  `9a45a47`; reuse global tokens and layout classes.
- Use `superpowers:test-driven-development` for every task and
  `superpowers:verification-before-completion` before each completion claim.
- Use this isolated test database only:

  ```bash
  export LEADTRACE_TEST_DATABASE_URL='postgresql+psycopg://zhangzhiyong@127.0.0.1:55440/leadtrace_reviewer_workspace_test'
  ```

- The full scientific corpus remains read-only. In this worktree, ignored
  `01_manifest` and `09_paper_review` links point to the main workspace source
  only so corpus-integrity tests can read the same immutable input.
- Do not modify generated CSV/JSON files under `source_pdfs`.
- Do not expose absolute `crop_path`, `source_pdf`, or storage paths through an
  API response.
- Do not keep an editable JSON textarea in the Reviewer flow.
- Each task ends with focused tests and one commit. Do not combine unrelated
  tasks into a single commit.

## Verification commands used throughout

Backend focused tests run from `leadtrace/backend`:

```bash
LEADTRACE_TEST_DATABASE_URL="$LEADTRACE_TEST_DATABASE_URL" \
  ../../.venv/bin/python -m pytest <test paths> -q
```

Frontend focused tests run from `leadtrace/frontend`:

```bash
npm test -- <test paths>
npm run typecheck
```

## Task 1: Add revisioned molecule proposals, frozen scopes, and attestations

**Files:**

- Create: `leadtrace/backend/app/molecule_proposals/__init__.py`
- Create: `leadtrace/backend/app/molecule_proposals/models.py`
- Create: `leadtrace/backend/migrations/versions/0018_reviewer_scientific_workspace.py`
- Modify: `leadtrace/backend/app/revisions/models.py`
- Modify: `leadtrace/backend/app/reviews/models.py`
- Modify: `leadtrace/backend/migrations/env.py`
- Modify: `leadtrace/backend/app/releases/aggregate.py`
- Modify: `leadtrace/backend/app/releases/validation.py`
- Modify: `leadtrace/backend/app/releases/manifest.py`
- Modify: `leadtrace/backend/app/releases/export.py`
- Test: `leadtrace/backend/tests/db/test_migrations.py`
- Create: `leadtrace/backend/tests/molecule_proposals/test_models.py`

**Step 1: Write failing model and migration tests**

Add tests that assert:

```python
assert ObjectKind.MOLECULE_PROPOSAL.value == "molecule_proposal"
assert MoleculeProposalDisposition.PENDING.value == "pending"
assert MoleculeProposalDisposition.NOT_APPLICABLE.value == "not_applicable"
```

Migration tests must upgrade an empty PostgreSQL database to head and assert:

- one Alembic head named `0018_reviewer_scientific_workspace`;
- `molecule_proposals` has Paper, Visual Object, proposal key, model-run key,
  crop asset, and source Region foreign keys;
- `(paper_id, visual_object_id, proposal_key, model_run_key)` is unique;
- `paper_review_scopes` has one immutable row per changeset, a JSONB snapshot,
  a 64-character hash, and base Release/Paper foreign keys;
- `paper_review_attestations` is append-only and records changeset version,
  scope hash, Reviewer, item/blocker counts, statement, and timestamp;
- `object_revisions.proposal_disposition` accepts exactly `pending`,
  `accepted`, `corrected`, `rejected`, and `not_applicable`;
- Release/revision object-kind constraints accept `molecule_proposal`.

**Step 2: Run the tests and verify RED**

```bash
cd leadtrace/backend
LEADTRACE_TEST_DATABASE_URL="$LEADTRACE_TEST_DATABASE_URL" \
  ../../.venv/bin/python -m pytest \
  tests/molecule_proposals/test_models.py \
  tests/db/test_migrations.py -q
```

Expected: collection/import or migration assertions fail because the new enum,
models, and migration do not exist.

**Step 3: Implement the minimal schema**

Add:

```python
class MoleculeProposalDisposition(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"


class MoleculeProposal(RevisionedObject):
    __tablename__ = "molecule_proposals"
    # identity columns and uniqueness described above
    __mapper_args__ = {
        "polymorphic_identity": ObjectKind.MOLECULE_PROPOSAL,
    }
```

Add `ObjectKind.MOLECULE_PROPOSAL`, the dedicated disposition column/index on
`ObjectRevision`, `PaperReviewScope`, and `PaperReviewAttestation`. Scope and
attestation snapshots are append-only at the ORM and database level; downgrade
must refuse while any proposal/scope/attestation rows exist, then remove the
new constraints/tables/columns in dependency order.

Register the model in Alembic metadata and every Release kind-to-model map.
Keep `ChangesetItem.object_kind` and `ReleaseItem.object_kind` length 24 because
`molecule_proposal` fits.

**Step 4: Run the focused tests and metadata comparison**

Expected: all focused tests pass and Alembic metadata matches the migrated
schema.

**Step 5: Commit**

```bash
git add leadtrace/backend/app/molecule_proposals \
  leadtrace/backend/app/revisions/models.py \
  leadtrace/backend/app/reviews/models.py \
  leadtrace/backend/app/releases/aggregate.py \
  leadtrace/backend/app/releases/validation.py \
  leadtrace/backend/app/releases/manifest.py \
  leadtrace/backend/app/releases/export.py \
  leadtrace/backend/migrations/env.py \
  leadtrace/backend/migrations/versions/0018_reviewer_scientific_workspace.py \
  leadtrace/backend/tests/molecule_proposals \
  leadtrace/backend/tests/db/test_migrations.py
git commit -m "feat: add reviewer proposal and attestation schema"
```

## Task 2: Import proposal evidence without mutating source files

**Files:**

- Modify: `leadtrace/backend/app/imports/readers/visuals.py`
- Modify: `leadtrace/backend/app/imports/readers/__init__.py`
- Modify: `leadtrace/backend/app/imports/reconcile.py`
- Modify: `leadtrace/backend/app/imports/service.py`
- Modify: `leadtrace/backend/app/releases/service.py`
- Modify: `leadtrace/backend/app/releases/aggregate.py`
- Test: `leadtrace/backend/tests/imports/test_readers.py`
- Test: `leadtrace/backend/tests/imports/test_reconcile.py`
- Test: `leadtrace/backend/tests/imports/test_service.py`
- Test: `leadtrace/backend/tests/releases/test_baseline_publish.py`

**Step 1: Write failing reader/import tests**

Create fixture rows with quoted `token_confidences` JSON and assert the reader
preserves it structurally, not as a lossy comma-split string. Assert that an
import creates a `MoleculeProposal` linked to the correct Paper/Visual Object,
and its first approved revision contains immutable machine fields:

```python
assert snapshot["raw_smiles"] == "CCO"
assert snapshot["token_confidences"] == [{"token": "C", "confidence": 0.9}]
assert snapshot["model_version"] == "ocsr-v1"
assert revision.proposal_disposition is MoleculeProposalDisposition.PENDING
```

Also assert:

- proposal rows with an unknown object/Paper fail reconciliation;
- raw absolute crop paths never appear in the safe normalized snapshot;
- proposal and crop content hashes contribute to the import fingerprint;
- existing aggregate acceptance counts do not change merely because proposals
  were added;
- a newly published baseline includes proposal ReleaseItems but remains
  `unverified`.

**Step 2: Run focused tests and verify RED**

```bash
cd leadtrace/backend
LEADTRACE_TEST_DATABASE_URL="$LEADTRACE_TEST_DATABASE_URL" \
  ../../.venv/bin/python -m pytest \
  tests/imports/test_readers.py \
  tests/imports/test_reconcile.py \
  tests/imports/test_service.py \
  tests/releases/test_baseline_publish.py -q
```

**Step 3: Add the proposal reader and reconciliation rules**

Add:

```python
def read_molecule_proposal_records(source_root: Path) -> list[StagedSourceRecord]:
    return read_csv_records(
        source_root,
        f"{AUTO_FILL}/first_page_molecule_proposals.csv",
        record_type="molecule_proposal",
        id_field="object_id",
    )
```

Before building the source record, parse and validate token-confidence JSON,
normalize status fields, convert the crop path to a manifest-relative asset
reference, and derive a stable proposal key/model-run key. Add proposals to
`BaselineSourceData.object_records` and fingerprint records, but keep the public
corpus/lineage/structure acceptance counters unchanged.

**Step 4: Create proposal identities and approved machine revisions**

Resolve the source `object_id` through the imported Visual Object map, reject
Paper mismatches, create the proposal identity, store the immutable machine
payload in the revision, and link the crop via `ImportAssetLink`. The initial
disposition is `pending` regardless of a legacy text `review_status`; legacy
status remains provenance, not a human decision in LeadTrace.

**Step 5: Include proposal revisions in baseline publication safely**

Update baseline Release item creation, aggregate model maps, validation, export,
restore, and artifact capture. Confirm that proposal presence never increments
`human_review.numerator`.

**Step 6: Run focused tests and commit**

```bash
git add leadtrace/backend/app/imports leadtrace/backend/app/releases \
  leadtrace/backend/tests/imports leadtrace/backend/tests/releases/test_baseline_publish.py
git commit -m "feat: import immutable molecule proposals"
```

## Task 3: Materialize source Regions, crops, and initial object bindings

**Files:**

- Modify: `leadtrace/backend/app/imports/reconcile.py`
- Modify: `leadtrace/backend/app/imports/service.py`
- Modify: `leadtrace/backend/app/imports/readers/visuals.py`
- Modify: `leadtrace/backend/app/visual_objects/models.py`
- Modify: `leadtrace/backend/app/releases/manifest.py`
- Test: `leadtrace/backend/tests/imports/test_service.py`
- Test: `leadtrace/backend/tests/visual_objects/test_bindings.py`
- Test: `leadtrace/backend/tests/releases/test_task21_red.py`

**Step 1: Write failing Region/crop binding tests**

For a first-page object fixture with candidate page bounds and local normalized
bounds, assert import creates:

- a Paper-local `VisualRegion` revision with page, normalized x0/y0/x1/y1,
  rotation 0, candidate/object provenance, and the source PDF asset;
- one published VisualObject-to-Region binding;
- one primary VisualObject-to-crop-asset binding;
- one proposal-to-crop association when a proposal exists;
- no binding that crosses a Paper boundary.

The test must use a real small PDF fixture so PyMuPDF page width/height can
normalize the source point coordinates.

**Step 2: Run focused tests and verify RED**

Expected: no Region or published bindings are created by the current importer.

**Step 3: Implement safe geometry and binding materialization**

Normalize the object box as:

```python
candidate_width = x1 - x0
candidate_height = y1 - y0
object_x0 = x0 + local_x0 * candidate_width
object_y0 = y0 + local_y0 * candidate_height
object_x1 = x0 + local_x1 * candidate_width
object_y1 = y0 + local_y1 * candidate_height
bounds = (
    object_x0 / page_width,
    object_y0 / page_height,
    object_x1 / page_width,
    object_y1 / page_height,
)
```

Here `x0/y0/x1/y1` are the candidate box in PDF points from
`auto_fill/first_page_molecule_objects.csv`, while
`local_x0/local_y0/local_x1/local_y1` are the object's normalized bounds
inside that candidate crop. Divide the composed object coordinates by the
PyMuPDF source-page dimensions, never by candidate-crop pixel dimensions.
Reject inverted/out-of-range local bounds before composing them.

Use `RegionBounds` validation after normalization. Invalid/missing geometry does
not invent a Region; it leaves a deterministic `localization` blocker in the
Visual Object snapshot. Create baseline bindings with deterministic logical
keys so artifact-manifest capture and re-import are idempotent.

Map only source object types with an exact LeadTrace semantic equivalent;
unknown/source-specific types remain `uncertain` and retain the raw type in the
revision provenance.

**Step 4: Run focused tests and commit**

```bash
git add leadtrace/backend/app/imports leadtrace/backend/app/visual_objects \
  leadtrace/backend/app/releases/manifest.py \
  leadtrace/backend/tests/imports/test_service.py \
  leadtrace/backend/tests/visual_objects/test_bindings.py \
  leadtrace/backend/tests/releases/test_task21_red.py
git commit -m "feat: bind imported molecule objects to source regions"
```

## Task 4: Add typed molecule-proposal review endpoints

**Files:**

- Create: `leadtrace/backend/app/molecule_proposals/service.py`
- Create: `leadtrace/backend/app/molecule_proposals/router.py`
- Modify: `leadtrace/backend/app/main.py`
- Modify: `leadtrace/backend/app/reviews/service.py`
- Modify: `leadtrace/backend/app/reviews/schemas.py`
- Modify: `leadtrace/backend/app/revisions/diff.py`
- Create: `leadtrace/backend/tests/molecule_proposals/test_service.py`
- Create: `leadtrace/backend/tests/molecule_proposals/test_api.py`
- Modify: `leadtrace/backend/tests/security/test_route_permission_matrix.py`

**Step 1: Write failing service and HTTP tests**

Cover `GET /api/v1/papers/{paper_id}/molecule-proposals` and
`PATCH /api/v1/papers/{paper_id}/molecule-proposals/{proposal_id}`. Assert:

- Visitor receives 403/hidden resource behavior;
- unassigned Reviewer receives 404;
- assigned Reviewer and Admin can read safe machine fields and asset content
  URLs, never filesystem paths;
- raw machine fields are absent from the PATCH schema and extra fields return
  422;
- accepted/corrected must pass existing RDKit validation and point to a
  same-Paper Compound/Structure;
- rejected/not applicable require a non-empty rationale;
- stale `expected_version` returns `REVISION_CONFLICT`;
- every write adds/updates the proposal changeset item, creates an immutable
  ObjectRevision, increments the changeset version, and emits an audit event.

**Step 2: Run tests and verify RED**

```bash
cd leadtrace/backend
LEADTRACE_TEST_DATABASE_URL="$LEADTRACE_TEST_DATABASE_URL" \
  ../../.venv/bin/python -m pytest tests/molecule_proposals \
  tests/security/test_route_permission_matrix.py -q
```

**Step 3: Implement the typed service**

The mutation request accepts only:

```python
class MoleculeProposalUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    disposition: MoleculeProposalDisposition
    reviewed_smiles: str | None = Field(default=None, max_length=10000)
    selected_component_smiles: str | None = Field(default=None, max_length=10000)
    compound_id: UUID | None = None
    resulting_structure_id: UUID | None = None
    rationale: str | None = Field(default=None, max_length=2000)
    source_comparison: SourceComparison = SourceComparison.NOT_COMPARED
    source_verified: bool = False
```

Call `validate_structure()` for accepted/corrected values. Preserve the base
revision's machine fields verbatim and merge only Reviewer-owned fields. Return
validation, safe crop asset metadata/URL, revision ID, and new changeset version.

**Step 4: Register routes, update diff categories, run tests, and commit**

```bash
git add leadtrace/backend/app/molecule_proposals leadtrace/backend/app/main.py \
  leadtrace/backend/app/reviews leadtrace/backend/app/revisions/diff.py \
  leadtrace/backend/tests/molecule_proposals \
  leadtrace/backend/tests/security/test_route_permission_matrix.py
git commit -m "feat: add typed OCSR proposal review API"
```

## Task 5: Freeze the Paper review scope and enforce attestation

**Files:**

- Create: `leadtrace/backend/app/reviews/completeness.py`
- Create: `leadtrace/backend/app/reviews/attestations.py`
- Modify: `leadtrace/backend/app/reviews/service.py`
- Modify: `leadtrace/backend/app/reviews/router.py`
- Modify: `leadtrace/backend/app/reviews/schemas.py`
- Modify: `leadtrace/backend/app/approvals/service.py`
- Test: `leadtrace/backend/tests/reviews/test_completeness.py`
- Test: `leadtrace/backend/tests/reviews/test_service.py`
- Test: `leadtrace/backend/tests/reviews/test_api.py`
- Create: `leadtrace/backend/tests/approvals/__init__.py`
- Create: `leadtrace/backend/tests/approvals/test_service.py`

**Step 1: Write failing pure completeness tests**

Implement test fixtures for the ordered queue/blocker rules:

```text
localization_or_split
needs_ocsr
proposal_review
source_or_attachment
structure_assembly
complete
```

Assert one object receives only its highest-priority unresolved state. Assert
that unchanged, non-blocking base items need no object-level verified marker;
they are covered by the Paper attestation scope hash.

**Step 2: Write failing lifecycle tests**

Assert:

- scope creation pins every Paper ReleaseItem plus required imported proposal
  revision IDs in a canonical JSON snapshot and content hash;
- scope creation is idempotent and rejects a different base Release;
- a one-item changeset cannot submit without completeness and attestation;
- `POST /api/v1/review/changesets/{id}/attestation` checks version/scope/blockers,
  ensures the Paper changeset item, writes `normalized_values.review_status =
  "reviewed"`, and stores an append-only attestation at the resulting version;
- any subsequent mutation makes the previous attestation stale because its
  changeset version no longer matches;
- submit validates the current attestation, embeds its ID/scope/counts/statement
  in the frozen submission, then advances the changeset version;
- changes-requested/revised drafts require a new attestation;
- Admin approve revalidates the frozen attestation and rejects missing or
  tampered scope evidence.

**Step 3: Implement canonical scope and blocker calculation**

Use `canonical_content_hash()` or the existing canonical Release hashing
utility; do not define a second JSON canonicalization algorithm. A scope item
contains object/revision/kind/source/required/reason, never mutable display
data or absolute paths.

**Step 4: Implement the attestation endpoint and submission gate**

The endpoint request is:

```python
class PaperAttestationRequest(BaseModel):
    expected_version: int = Field(ge=1)
    scope_hash: str = Field(min_length=64, max_length=64)
    statement: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]
```

Generate `review_status=reviewed` server-side; remove the authority to set it
through an arbitrary Reviewer paper field. Return current progress,
attestation ID, and new changeset version.

**Step 5: Run tests and commit**

```bash
git add leadtrace/backend/app/reviews leadtrace/backend/app/approvals/service.py \
  leadtrace/backend/tests/reviews/test_completeness.py \
  leadtrace/backend/tests/reviews/test_service.py \
  leadtrace/backend/tests/reviews/test_api.py \
  leadtrace/backend/tests/approvals/__init__.py \
  leadtrace/backend/tests/approvals/test_service.py
git commit -m "feat: require Paper review attestation"
```

## Task 6: Recompute Paper and Release verification at publication

**Files:**

- Modify: `leadtrace/backend/app/releases/aggregate.py`
- Modify: `leadtrace/backend/app/releases/service.py`
- Modify: `leadtrace/backend/app/releases/validation.py`
- Modify: `leadtrace/backend/app/papers/repository.py`
- Modify: `leadtrace/backend/app/papers/service.py`
- Test: `leadtrace/backend/tests/releases/test_task21_red.py`
- Test: `leadtrace/backend/tests/releases/test_routes.py`
- Test: `leadtrace/backend/tests/api/test_published_papers.py`
- Test: `leadtrace/backend/tests/api/test_overview.py`

**Step 1: Write failing publication tests**

Start with a Release whose old metric is `0/N`, publish one approved attested
Paper changeset, and assert the successor is `1/N`, not copied `0/N`. Publish
all N attested Papers and assert `human_verified`. Also assert:

- object/proposal dispositions alone never increment the numerator;
- Paper `review_status=reviewed` without a valid approved attestation does not
  increment the numerator;
- approval before publication is not visible through Visitor APIs;
- historical Release metrics and Paper status remain unchanged;
- rollback recomputes from the target manifest rather than inheriting the
  current Release metric.

**Step 2: Run tests and verify RED**

Expected: `_metrics_with_operation()` copies the old human-review metric.

**Step 3: Implement one authoritative calculation**

Add `human_review_metric(session, release_items, provenance)` that sets:

```text
denominator = number of Paper ReleaseItems
numerator   = Paper ReleaseItems whose revision says reviewed and whose
              published provenance references a valid Reviewer attestation
              and Admin approval for the same submitted snapshot
```

Call it for baseline publication, changeset publication, evidence-only
successor publication, and rollback. Keep `release_verification_status()` as
the presentation mapping from metric values.

Replace Paper detail's current “count reviewed object snapshots” logic with one
Release-scoped Paper verification object.

**Step 4: Run tests and commit**

```bash
git add leadtrace/backend/app/releases leadtrace/backend/app/papers \
  leadtrace/backend/tests/releases leadtrace/backend/tests/api
git commit -m "fix: derive verification from attested Papers"
```

## Task 7: Add the version-consistent workspace and queue projections

**Files:**

- Create: `leadtrace/backend/app/reviews/workspace.py`
- Modify: `leadtrace/backend/app/reviews/router.py`
- Modify: `leadtrace/backend/app/reviews/schemas.py`
- Modify: `leadtrace/backend/app/approvals/service.py`
- Create: `leadtrace/backend/tests/reviews/test_workspace.py`
- Create: `leadtrace/backend/tests/reviews/test_molecule_queue.py`
- Test: `leadtrace/backend/tests/security/test_hidden_resources.py`

**Step 1: Write failing workspace API tests**

Test `GET /api/v1/review/changesets/{id}/workspace` returns one coherent
version with:

```json
{
  "changeset": {},
  "paper": {},
  "progress": {"scope_count": 0, "resolved_count": 0, "blocker_count": 0, "by_kind": {}},
  "document": {"url": ".../source-pdf?release_id=..."},
  "pages": [],
  "regions": [],
  "visual_objects": [],
  "molecule_proposals": [],
  "structures": [],
  "assets": [],
  "source_locators": [],
  "attestation": null
}
```

Assert every referenced entity belongs to the same Paper and base Release;
asset entries contain `/api/v1/assets/{id}/content`, dimensions/hash/access
level, and no storage/source path.

**Step 2: Write failing queue API tests**

Test `GET /api/v1/review/tasks/first-page-molecule-objects` supports status,
Paper, page, object type, blocker, cursor, and limit filters. The queue must:

- include only Papers assigned to the Reviewer, or all for Admin;
- derive state server-side using Task 5 rules;
- return one highest-priority state per Visual Object;
- carry Paper progress and the existing ReviewTask/changeset IDs;
- return `changeset_id = null` for an unstarted task without creating anything;
- never duplicate task, approval, or release state.

**Step 3: Implement projections with stable ordering**

Use one transaction and record the locked/read changeset version at start and
end; retry or return 409 if it changes during assembly. Order queue rows by
blocker priority, proposal min confidence, Paper priority, page, and stable
object key. Use cursor pagination based on that full tuple.

**Step 4: Extend Admin scientific evidence**

Return attestation/progress, before/after proposal and Structure data, Region
source context, and safe asset URLs. Default API representation supports
`changed_only=true` without losing the complete scope count.

**Step 5: Run tests and commit**

```bash
git add leadtrace/backend/app/reviews leadtrace/backend/app/approvals/service.py \
  leadtrace/backend/tests/reviews leadtrace/backend/tests/security/test_hidden_resources.py
git commit -m "feat: expose scientific review workspace projections"
```

## Task 8: Add evidence-only proposal backfill for an already published baseline

**Files:**

- Create: `leadtrace/backend/app/imports/proposal_backfill.py`
- Create: `leadtrace/backend/app/cli/import_proposals.py`
- Modify: `leadtrace/backend/app/releases/models.py`
- Modify: `leadtrace/backend/app/releases/service.py`
- Modify: `leadtrace/backend/app/releases/router.py`
- Modify: `leadtrace/backend/migrations/versions/0018_reviewer_scientific_workspace.py`
- Create: `leadtrace/backend/tests/imports/test_proposal_backfill.py`
- Modify: `leadtrace/backend/tests/releases/test_routes.py`

**Step 1: Write failing backfill tests**

Assert the operation:

- refuses any source fingerprint not tied to the current baseline import;
- stages/imports only missing proposal/Region/crop evidence;
- creates a successor Release by copying the current manifest and appending the
  new machine-evidence revisions;
- keeps `human_review` and `verification_status` unchanged/unverified;
- never changes historical Release manifests, revisions, or artifact hashes;
- is idempotent by Admin + operation key + request hash;
- refuses to silently rebase an active changeset; existing tasks keep their old
  base and Admin must supersede/recreate them explicitly.

**Step 2: Run tests and verify RED**

**Step 3: Implement the explicit Admin operation**

Add operation type `machine_evidence` to the DB constraint. Require an enabled
Admin, recent reauthentication, CSRF for HTTP, and idempotency key. The CLI
accepts source root and managed asset root but never prints credentials or
absolute path data in its result.

**Step 4: Run tests and commit**

```bash
git add leadtrace/backend/app/imports/proposal_backfill.py \
  leadtrace/backend/app/cli/import_proposals.py \
  leadtrace/backend/app/releases \
  leadtrace/backend/migrations/versions/0018_reviewer_scientific_workspace.py \
  leadtrace/backend/tests/imports/test_proposal_backfill.py \
  leadtrace/backend/tests/releases/test_routes.py
git commit -m "feat: backfill proposal evidence into successor releases"
```

## Task 9: Add typed frontend workspace and queue contracts

**Files:**

- Modify: `leadtrace/frontend/src/api/schema.ts`
- Modify: `leadtrace/frontend/src/review/api.ts`
- Create: `leadtrace/frontend/src/review/workspace/types.ts`
- Create: `leadtrace/frontend/src/review/workspace/useWorkspace.ts`
- Test: `leadtrace/frontend/tests/review-workflow.spec.ts`
- Create: `leadtrace/frontend/tests/workspace-contract.spec.ts`

**Step 1: Write failing Zod/API tests**

Create representative workspace, queue, proposal, progress, source-locator,
asset, and attestation payloads. Assert malformed cross-Paper IDs, raw
`crop_path`, negative progress, unknown dispositions, and invalid bounds fail
parsing.

Assert typed client methods use:

```text
GET  /api/v1/review/changesets/{id}/workspace
GET  /api/v1/review/tasks/first-page-molecule-objects
GET  /api/v1/papers/{paper}/molecule-proposals
PATCH /api/v1/papers/{paper}/molecule-proposals/{proposal}
POST /api/v1/review/changesets/{id}/attestation
```

**Step 2: Run tests and verify RED**

```bash
cd leadtrace/frontend
npm test -- tests/workspace-contract.spec.ts tests/review-workflow.spec.ts
```

**Step 3: Implement Zod schemas and state composition**

`useWorkspace` owns load generation, selected page/Region/Object/Proposal,
deep-link parsing, version updates, and safe refresh after conflicts. It does
not duplicate the existing autosave/recovery implementation; field editors
call typed mutations and then replace the returned version/entity.

**Step 4: Run tests, typecheck, and commit**

```bash
git add leadtrace/frontend/src/api/schema.ts leadtrace/frontend/src/review \
  leadtrace/frontend/tests/workspace-contract.spec.ts \
  leadtrace/frontend/tests/review-workflow.spec.ts
git commit -m "feat: add typed scientific workspace client"
```

## Task 10: Add the first-page molecule-object queue under review tasks

**Files:**

- Create: `leadtrace/frontend/src/review/tasks/MoleculeObjectQueue.vue`
- Modify: `leadtrace/frontend/src/review/tasks/TaskListPage.vue`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Test: `leadtrace/frontend/tests/review-workflow.spec.ts`
- Test: `leadtrace/frontend/e2e/accessibility.spec.ts`

**Step 1: Write failing queue UI tests**

Assert `/review/tasks` has two tabs/segments, Paper task counts, queue status
counts, filters, crop thumbnails with alt text, Paper progress, collapsed
completed group, loading/empty/error states, and no new top-level navigation.

Clicking a row with a changeset must navigate to:

```text
/review/changesets/{id}?view=ocsr&page={page}&object={object}&proposal={proposal}
```

An unstarted task routes through the existing changeset-start path with target
query parameters preserved; it does not create a task or changeset on row
render.

**Step 2: Run tests and verify RED**

**Step 3: Implement the dense queue**

Use shared panel/table/filter/status classes. Status text and icons must be
readable without color. Keep completed collapsed by default and persist filters
in the URL. Do not display “object verified”.

**Step 4: Run tests and commit**

```bash
git add leadtrace/frontend/src/review/tasks leadtrace/frontend/src/styles \
  leadtrace/frontend/tests/review-workflow.spec.ts \
  leadtrace/frontend/e2e/accessibility.spec.ts
git commit -m "feat: add molecule objects to review task queue"
```

## Task 11: Build the three-pane Paper workspace shell and evidence canvas

**Files:**

- Create: `leadtrace/frontend/src/review/workspace/PaperWorkspace.vue`
- Create: `leadtrace/frontend/src/review/workspace/WorkspaceContextRail.vue`
- Create: `leadtrace/frontend/src/review/workspace/WorkspaceEvidenceCanvas.vue`
- Create: `leadtrace/frontend/src/review/workspace/WorkspaceActionBar.vue`
- Modify: `leadtrace/frontend/src/review/changesets/ChangesetPage.vue`
- Modify: `leadtrace/frontend/src/pdf-viewer/PdfReviewCanvas.vue`
- Modify: `leadtrace/frontend/src/pdf-viewer/RegionOverlay.vue`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Test: `leadtrace/frontend/tests/review-workflow.spec.ts`
- Test: `leadtrace/frontend/tests/regions.spec.ts`
- Create: `leadtrace/frontend/tests/workspace-layout.spec.ts`

**Step 1: Write failing shell/deep-link tests**

Assert the left rail, evidence canvas, typed inspector slot, and sticky action
bar exist; route query selects the exact page/object/proposal; next/previous
unresolved controls update selection and query without a reload.

Assert the evidence canvas supports whole-page/crop toggle, stable crop/RDKit
preview dimensions, selected Region synchronization, and text fallbacks for
missing PDF/crop/drawing.

**Step 2: Run tests and verify RED**

**Step 3: Implement shell and selection behavior**

Keep tabs for Overview, PDF/Regions, Molecule Objects, OCSR/Structures,
Scientific Data, Diff, and Submit. On desktop use 260-300px rail and 340-420px
inspector; on tablet collapse the rail; on mobile make precision Region drawing
read-only with an explicit desktop-required message.

Extend PDF Region interaction to emit normalized create/move/resize results.
Keep PDF geometry component-local; use global layout/control classes elsewhere.

**Step 4: Run tests, typecheck, and commit**

```bash
git add leadtrace/frontend/src/review/workspace \
  leadtrace/frontend/src/review/changesets/ChangesetPage.vue \
  leadtrace/frontend/src/pdf-viewer leadtrace/frontend/src/styles/layouts.css \
  leadtrace/frontend/tests/review-workflow.spec.ts \
  leadtrace/frontend/tests/regions.spec.ts \
  leadtrace/frontend/tests/workspace-layout.spec.ts
git commit -m "feat: build scientific review workspace shell"
```

## Task 12: Integrate typed Region and Visual Object editing

**Files:**

- Create: `leadtrace/frontend/src/review/workspace/RegionInspector.vue`
- Create: `leadtrace/frontend/src/review/workspace/VisualObjectInspector.vue`
- Modify: `leadtrace/frontend/src/visual-objects/ObjectInspector.vue`
- Modify: `leadtrace/frontend/src/visual-objects/ImageBindings.vue`
- Modify: `leadtrace/frontend/src/visual-objects/CompoundBindings.vue`
- Modify: `leadtrace/frontend/src/review/api.ts`
- Test: `leadtrace/frontend/tests/regions.spec.ts`
- Test: `leadtrace/frontend/tests/molecule-objects.spec.ts`
- Test: `leadtrace/frontend/tests/workspace-layout.spec.ts`

**Step 1: Write failing inspector tests**

Cover Region key/page/bounds/rotation, create/move/save, duplicate, split,
tombstone, restore, validation errors, and version conflicts. Cover object type,
label, Region/asset/compound bindings, primary crop, operation badges, and
source-locator jumps.

Assert controls are disabled in submitted/approved/published states and raw
JSON is absent.

**Step 2: Run tests and verify RED**

**Step 3: Wire typed APIs**

Reuse existing Paper-scoped Region/Visual Object endpoints. Each successful
mutation updates workspace version and only the affected projection. On a 409,
open the existing conflict UI; never replay a geometry mutation silently.

**Step 4: Run tests and commit**

```bash
git add leadtrace/frontend/src/review/workspace leadtrace/frontend/src/review/api.ts \
  leadtrace/frontend/src/visual-objects leadtrace/frontend/tests
git commit -m "feat: add Region and molecule object inspectors"
```

## Task 13: Integrate OCSR proposal and Structure review

**Files:**

- Create: `leadtrace/frontend/src/review/workspace/MoleculeProposalInspector.vue`
- Create: `leadtrace/frontend/src/review/workspace/StructureInspector.vue`
- Modify: `leadtrace/frontend/src/structures/StructureEditor.vue`
- Modify: `leadtrace/frontend/src/structures/StructureComparison.vue`
- Modify: `leadtrace/frontend/src/review/changesets/ScientificEditors.vue`
- Modify: `leadtrace/frontend/src/review/api.ts`
- Test: `leadtrace/frontend/tests/structure-editor.spec.ts`
- Test: `leadtrace/frontend/tests/scientific-editors.spec.ts`
- Test: `leadtrace/frontend/tests/workspace-layout.spec.ts`

**Step 1: Write failing OCSR/Structure tests**

Assert crop, raw SMILES, confidence summary, low-confidence tokens, inference
error, machine canonical SMILES, RDKit status/drawing, reviewed SMILES, source
comparison, and resulting Compound/Structure are all visible in one context.

Test accept, correct+validate, reject, and not-applicable. Accept/correct cannot
save an invalid structure; reject/not-applicable require rationale. Test
multicomponent selection, mismatch, and drawing error fallbacks.

**Step 2: Run tests and verify RED**

**Step 3: Implement typed proposal and structure inspectors**

Machine fields are read-only. Reviewer fields call proposal PATCH and existing
Structure validate/draw/create/update endpoints. Compare crop, machine drawing,
and reviewed drawing in stable preview frames. Display scientific state chips,
never a per-object verified chip.

**Step 4: Extend ScientificEditors and commit**

`ScientificEditors` recognizes Region, Visual Object, Molecule Proposal, and
Structure items and delegates to typed components. It may show a read-only
Admin debug snapshot behind a disclosure, but must not emit arbitrary snapshot
updates from JSON.

```bash
git add leadtrace/frontend/src/review leadtrace/frontend/src/structures \
  leadtrace/frontend/tests/scientific-editors.spec.ts \
  leadtrace/frontend/tests/structure-editor.spec.ts \
  leadtrace/frontend/tests/workspace-layout.spec.ts
git commit -m "feat: add OCSR and structure review inspectors"
```

## Task 14: Add Paper attestation and evidence-first Admin approval UI

**Files:**

- Modify: `leadtrace/frontend/src/review/changesets/SubmissionPage.vue`
- Modify: `leadtrace/frontend/src/review/changesets/ChangesetPage.vue`
- Modify: `leadtrace/frontend/src/approvals/ApprovalCenterPage.vue`
- Modify: `leadtrace/frontend/src/approvals/api.ts`
- Modify: `leadtrace/frontend/src/review/workspace/WorkspaceActionBar.vue`
- Test: `leadtrace/frontend/tests/review-workflow.spec.ts`
- Test: `leadtrace/frontend/tests/approval-release.spec.ts`
- Test: `leadtrace/frontend/e2e/review-minimal.spec.ts`

**Step 1: Write failing attestation/submission tests**

Assert the sticky bar and Submit tab show resolved/scope/blocker counts, stale
attestation state, disabled reasons, exact attestation statement, and current
scope hash. Submission remains disabled until autosave is settled, blockers are
zero, Paper attestation is current, and typed editor validation passes.

**Step 2: Write failing Admin evidence tests**

Admin defaults to changed/non-normal items, can expand complete scope, sees
attestation identity/hash and before/after Region/Proposal/Structure evidence,
and can anchor comments. Approve is disabled when server evidence is invalid;
approved state says “已批准，待发布”.

**Step 3: Implement UI and remove editable JSON**

Replace the Paper `review_status` text input with server-generated attestation
status. Remove `.advanced-snapshots` editable textareas from Reviewer mode.
Preserve offline/conflict recovery for remaining typed metadata fields.

**Step 4: Run tests and commit**

```bash
git add leadtrace/frontend/src/review leadtrace/frontend/src/approvals \
  leadtrace/frontend/tests/review-workflow.spec.ts \
  leadtrace/frontend/tests/approval-release.spec.ts \
  leadtrace/frontend/e2e/review-minimal.spec.ts
git commit -m "feat: enforce attested review submission UI"
```

## Task 15: Add published crop, source, RDKit, and Paper verification context

**Files:**

- Modify: `leadtrace/backend/app/papers/service.py`
- Modify: `leadtrace/backend/app/papers/router.py`
- Modify: `leadtrace/frontend/src/api/schema.ts`
- Modify: `leadtrace/frontend/src/papers/PaperDetailPage.vue`
- Create: `leadtrace/frontend/src/papers/PublishedSourceContext.vue`
- Modify: `leadtrace/frontend/src/papers/QualitySummary.vue`
- Test: `leadtrace/backend/tests/api/test_published_papers.py`
- Test: `leadtrace/frontend/tests/published-pages.spec.ts`
- Test: `leadtrace/frontend/e2e/visitor.spec.ts`

**Step 1: Write failing Release-scoped detail tests**

Assert the public response includes only release-pinned Visual Objects,
published primary crop assets, safe source page/Region locators, published
Structure drawing URLs, and Paper verification. Draft proposal/raw diagnostics,
unpublished asset bindings, local paths, and Admin pending-publication state
must never appear.

**Step 2: Run tests and verify RED**

**Step 3: Implement the safe projection and UI**

Paper detail shows:

- Paper-level “AI 提取基线 / 未经人工核验” or “人工核验数据集 / 已核验”;
- source page/crop thumbnails with accessible open-source actions;
- canonical SMILES, RDKit drawing, scientific Structure state, and source
  locator;
- release-pinned progress diagnostics without object-level verified badges.

Reviewer/Admin additionally see an “在核查工作台中打开” deep-link when an
active accessible changeset exists; Visitor never sees that internal link.

**Step 4: Run tests and commit**

```bash
git add leadtrace/backend/app/papers leadtrace/backend/tests/api/test_published_papers.py \
  leadtrace/frontend/src/api/schema.ts leadtrace/frontend/src/papers \
  leadtrace/frontend/tests/published-pages.spec.ts \
  leadtrace/frontend/e2e/visitor.spec.ts
git commit -m "feat: restore published scientific source context"
```

## Task 16: Complete accessibility, responsive behavior, and end-to-end verification

**Files:**

- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Modify: `leadtrace/frontend/e2e/accessibility.spec.ts`
- Modify: `leadtrace/frontend/e2e/concurrency.spec.ts`
- Modify: `leadtrace/frontend/e2e/review-minimal.spec.ts`
- Modify: `leadtrace/frontend/e2e/visitor.spec.ts`
- Modify: `leadtrace/README.md`

**Step 1: Add failing accessibility/responsive E2E coverage**

Cover keyboard focus order, N/P unresolved navigation outside text inputs,
aria-live autosave/conflict/completeness updates, color-independent status,
desktop three-pane layout, tablet collapsible inspector, mobile read-oriented
mode, no horizontal page overflow, missing-image fallback, and reduced motion.

**Step 2: Add a complete workflow smoke test**

```text
Admin publishes unverified AI baseline
-> assigns Paper
-> Reviewer enters from molecule-object queue
-> edits Region and binding
-> accepts/corrects OCSR and creates Structure/RDKit drawing
-> resolves scope and attests Paper
-> submits
-> Admin reviews evidence and approves
-> Admin publishes successor Release
-> Visitor sees Paper/Release human verification and published source context
```

Assert no object-level verified badge and no editable JSON textarea appears.

**Step 3: Run the full verification suite**

```bash
cd leadtrace/backend
LEADTRACE_TEST_DATABASE_URL="$LEADTRACE_TEST_DATABASE_URL" \
  ../../.venv/bin/python -m pytest

cd ../frontend
npm test
npm run typecheck
npm run build
npx playwright test --project=chromium

cd ../..
git diff --check
git status --short
```

Expected: all backend/frontend/E2E tests pass, production build succeeds, diff
check is clean, and only intended files are changed.

**Step 4: Update rollout documentation**

Document the `0018` migration, proposal import/backfill command, feature flag or
cutover procedure, protected asset requirements, and how to verify
`human_review` counts before publishing. State that existing active changesets
are never silently rebased.

**Step 5: Commit**

```bash
git add leadtrace/frontend/src/styles leadtrace/frontend/e2e leadtrace/README.md
git commit -m "test: verify reviewer scientific workspace"
```

## Completion gate

Before claiming completion:

1. Use `superpowers:requesting-code-review` and address all verified findings.
2. Re-run the full Task 16 verification commands after the last code change.
3. Use `superpowers:verification-before-completion` and cite actual counts.
4. Use `superpowers:finishing-a-development-branch` to present merge/PR/cleanup
   choices; do not merge into `main` without the user's direction.
