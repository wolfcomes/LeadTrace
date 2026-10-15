# Supplement article metadata in existing drafts and submissions

Use this operation only for an explicitly authorized administrative supplement.
It is an operator service, not a Reviewer impersonation or a scientific approval.
The normal Reviewer editor remains the path for human corrections. Select the
operator entry below from the actual current workspace state; do not create a
technical submission merely to fill an editable draft.

## Add missing metadata to an editable draft

For an authorized batch, sort successfully prefilled articles by paper key and
freeze each workspace ID/version, `canonical_snapshot_hash(build_paper_snapshot(...))`,
source SHA/page identity and existing article metadata. Keep already complete
articles unchanged. Preserve each actual producer run, its fresh scientific
review and the final accepted proposal in the ignored run directory. The
supervisor reads structured outputs and identity metadata, not source pages or
native scientific reasoning logs. Missing information stays absent; reported SI
or bibliographic gaps do not justify invented fields.

After a verified production backup and rehearsal, call this operator in one
transaction with an enabled Admin actor:

```python
from app.publications.draft_metadata import supplement_draft_metadata

receipt = supplement_draft_metadata(
    session, workspace_id=workspace_id,
    expected_workspace_version=baseline_version,
    expected_snapshot_hash=baseline_hash,
    updates=accepted_metadata_patch, reason=authorized_reason,
    actor=admin, request_id=unique_request_id, provenance=runtime_provenance,
)
```

The patch accepts only `ARTICLE_METADATA_DEFAULTS` fields. Scalars must be
missing. A partial `research_profile` fills absent/empty groups; populated groups
remain exact, with safe appended evidence as the only supported change. A full
profile is also accepted when all populated groups are retained exactly. Do not
add `molecular_forms`; retain existing legacy values. Populated PDB references
allow appended evidence only, preserving every existing entry, key and order.
New molecule types use the fixed main/feature vocabulary below with evidence.
Article schemas, main-source SHA/pages and crop geometry are validated. New SI
evidence requires a separately verified SI source and is not accepted by this
main-source-only operator. Empty/default patches, overwrites, stale baselines,
removed/read-only workspaces, corrupt sources and active AI/crop jobs are rejected.

`provenance` is a valid `ProvenanceInput` tied to the actual run: source and final
candidate file SHA, acceptance-evidence SHA, frozen guide-bundle SHA, adapter,
model, completion time, eligible production stage and `completed`/`partial`
outcome are required. Preserve truthful verification strength: Codex runs use
`requested_only`; do not invent `request_observed`. Failed/mismatched runs cannot
be delivered. The service records this evidence in audit without manufacturing
an `AiProvenance` row. The operator may append separately verified repair and
independent-review provenance in the same transaction. Use the receipt's version
as the repair's applied version; independently record the final snapshot hash
after provenance append, since `receipt.after_hash` describes the earlier
post-metadata snapshot.

The draft version increases once, bibliography becomes pending with its existing
note preserved, and ordinary draft task status/assignee remain unchanged.
Compound/Lineage data, viewing signatures, receipts and other sections stay
unchanged. No submission or decision is created. An identical successful request
returns its stored receipt; reusing its identity for a different payload fails.
Let exceptions roll back the transaction and inspect a fresh baseline rather than
resetting versions or forcing an old proposal onto new human edits.

## Explicit supplemental revision of an already published article

This requires separate user authorization. Supply `allow_published_revision=True`
and the exact `expected_published_version_id` in addition to the frozen workspace
hash/version above. The service requires the same approved workspace to match
the current published scientific snapshot and rejects another active generation.
It reopens that workspace/task as editing/assigned, retaining the original
Reviewer, scientific IDs, confirmations and receipts. Versions increment normally.
The current published pointer, frozen published snapshot, old submissions and
real decisions are unchanged; public APIs continue to serve the old published
version until the Reviewer submits and Admin approves the supplemental revision.
An actual `workspace.metadata_revision_started` event/audit records this transition.

## Approval display and attribution

Draft delivery records `bibliography.ai_supplement` with AI actor kind and no
human actor ID, plus an actual Admin `paper.article_metadata_supplement` audit
binding the workspace, event ID, canonical before/after payload hash, source,
request identity and validated runtime provenance. Only additive deltas with
that exact verified binding are excluded from Reviewer modification counts.
The projection applies changed field/group/evidence paths; it never copies an
entire research profile over unrelated human changes. This works in the first
Reviewer round even when the AI fill follows human edits, as well as later
rounds. Human corrections after AI fill stay visible. Invalid/unbound histories
warn and remain in the main comparison when a reliable baseline exists. If an
unverified older event prevents safe starting-state reconstruction, the comparison
is explicitly unavailable and the complete immutable submission stays inspectable.

Supplement additions appear in one folded context per before/after phase,
combined with existing verified technical supplement history. Additions to a
returned or reopened draft can be inspected from the latest immutable Reviewer
submission before resubmission; they do not become an approvable version.
Reviewer-only navigation and legacy API shapes remain unchanged.

## Supplement an existing pending submission

1. Read fresh production submission/workspace metadata and record the submission
   ID, content hash, workspace version, DOI and article identity. Obtain missing
   fields from independently matched bibliographic records or the selected
   scientific runtime; retain the evidence and exact proposed patch. Do not copy
   Preview or trial records into production.
2. Take and verify a production backup. Rehearse the migration and supplement on
   a protected database restored from that backup. Never run test-reset suites
   against a production or acceptance database.
3. In one database transaction, load the enabled Admin actor and call
   `app.publications.metadata_supplement.supplement_metadata` with the recorded
   `submission_id`, `content_hash`, `expected_workspace_version`, `updates`,
   a clear administrative `reason`, and an operator `request_id`.
4. The service accepts missing article metadata, including source-bounded PDB
   mentions. Explicit cleanup of an existing Abstract note additionally requires
   its exact current value in `expected_existing={"abstract_note": old_value}`;
   other populated metadata cannot be replaced except through the explicitly
   scoped molecule-type classification mode below.
   Existing bibliography section notes are preserved by default. Removing a
   prior generated section note requires `expected_section_note=old_value` and
   an exact current-value match; an unexpected human edit is never cleared.
   It verifies that the live
   science and bibliography still match the frozen submission. It uses the
   existing request-changes decision to close the old submission, then creates
   a new pending submission attributed to Admin. The previous snapshot and hash
   remain unchanged. The new bibliography section is pending. Operator identity
   and the reason remain in history/audit; the visible article and submission
   notes receive no special administrator-supplement label or fabricated
   Reviewer confirmation.
   Compound/Lineage viewing receipts remain valid for unchanged scientific data.
5. After the final supplement in the authorized batch, call
   `app.publications.supplement_review.return_supplement_for_review` in a transaction,
   passing the latest `submission_id`, `content_hash`, `expected_workspace_version`,
   enabled Admin `actor`, clear `reason`, and `request_id`. Explain that only additions
   and their dependencies require checking; prior work is retained. The helper verifies
   the supplement chain and live baseline, then uses the normal request-changes
   service. It retains content, all section states/notes and viewing receipts, increments
   workflow versions normally, records the actual Admin actor, and is idempotent.
   Already-returned or superseded articles must not be reset or returned again using
   stale inputs. An identical completed helper request can be replayed safely.
6. Verify original snapshot hashes, unaffected scientific tables and confirmations,
   editable Reviewer draft state, `changes_requested` task state and audit chain.
   The technical snapshot is excluded from the Reviewer approval queue. The article
   remains accessible under All submissions with its original Reviewer date/note,
   separate folded additions, and the real subsequent return reason. Only a new
   genuine Reviewer submission becomes approvable; technical supplement approval
   is rejected even with the correct hash. Reviewer-only navigation uses
   `reviewer_rounds=true`. Invalid links show explicit warnings rather than silently
   hiding changes. No scientific approval or publication is created by this operation.

An identical request replays its existing replacement. A stale baseline,
non-Admin actor, non-metadata field, or attempt to replace a populated field
outside the supported exact-baseline modes is rejected. Let any
exception roll back the complete transaction. Do not change
versions, snapshots, assignments or confirmations to force an operation through.
Different follow-up corrections require fresh inspection and a separately
authorized operation; populated-field edits remain limited to the modes below.

## Evidence-only additions to populated metadata

For an authorized evidence backfill, pass `expected_evidence_baseline` to
`supplement_metadata`: a complete exact copy of each updated `research_profile`
or `pdb_references` field. `updates` contains the same complete fields with only
per-entry evidence appended. Existing groups, entry order, all non-evidence
fields and previous evidence must remain byte-shape-equivalent JSON. Do not use
`expected_existing`, section-note cleanup, or a generic populated-field replace.
The ordinary submission hash/workspace version/frozen content checks still apply.
Main-PDF pages and optional SHA values are checked against PaperSource. The old
submission remains immutable, and its replacement is unconfirmed; complete the
return-to-Reviewer step after the final supplement.
No scientific approval, deployment, or arbitrary metadata overwrite is implied.

## Missing metadata and evidence in one replacement

`expected_evidence_baseline` may cover a nonempty subset of `updates`. The matched
fields remain strictly evidence-only, including exact old JSON shape and order;
every other updated field must still be missing under the normal metadata
rules. This allows a new research profile or PMID and evidence for existing PDB
mentions to appear together in one immutable pending replacement. Empty or
non-subset baselines and replacement of any other populated field are rejected.
Evidence mode cannot be combined with Abstract-note or section-note cleanup.

For a batch, freeze the complete current pending queue and record per-paper
submission hash, workspace version and source identity. Verify already-completed
papers without adding duplicate excerpts. Keep each producer's candidate and
fresh review distinct; bind final patches to actual frozen guides, source hashes
and final revision self-checks. Missing SI and unsupported entries stay explicit.
Use a new run directory after a failed model invocation; do not overwrite frozen
tasks or replay completed applies. A provider authentication/balance failure is
not an extraction result and must not become an empty article patch.

## Reclassify molecule types in pending articles

Use this mode only when the user has explicitly authorized replacing the article
classification. Pass `expected_classification_baseline` as the exact full current
`research_profile` object (not a wrapper containing that field). `updates` must
contain only `research_profile`, with all groups except `modalities` unchanged,
including group presence, entry order, whitespace, nulls, omitted keys and prior
evidence. Only the `modalities` array may be replaced. This mode cannot be mixed
with `expected_existing`, `expected_evidence_baseline` or section-note cleanup.

Select at least one main type: 小分子抑制剂、小分子激动剂、小分子拮抗剂、
小分子反向激动剂、小分子激活剂、小分子调节剂（作用待细分）、PROTAC、分子胶、
其他、待明确. Optional supplementary features are 变构调节、共价作用、大环类、
肽／肽模拟物、前药. Labels cannot repeat. Every selected label needs its own
nonempty source explanation and evidence; 其他 and 待明确 also require a
`review_hint` explaining the classification. Classify the optimized series,
not background/comparator compounds. Do not infer inhibitor activity from the
legacy broad label 直接靶点调节 or treat a peptide as a conventional small molecule.
A peptide inhibitor can be 其他 (explain peptide inhibitor) + 肽／肽模拟物; include
大环类 only with support. Different series must be identified in explanations.

The service validates the entire profile and all supplied evidence, including
main-PDF page bounds/hash and crop geometry, while preserving the original JSON
shape after validation. It binds the full baseline into the idempotency identity,
checks the actual live profile and the usual frozen hash/workspace version, and
rejects an unchanged classification. Old submission snapshots stay immutable;
only a new pending, bibliography-unconfirmed replacement is created. A repeat of
the identical successful request returns that replacement. A changed proposal or
baseline requires a fresh current submission, never a forced version reset.

Freeze and review each proposed replacement with the selected scientific runtime
and a distinct fresh reviewer before applying. Rehearse against the verified
production backup, check the exact current queue and all proposal identities,
and verify unchanged non-classification scientific data and old snapshots after
application. Missing SI and unresolved classifications remain explicit. This is
not scientific approval and grants no authority for unrelated data edits.

The ordinary manual editor uses the same 15 labels. When a nonempty label
selection changes it must include a main type and contain no duplicates. Empty
classification remains allowed in ordinary drafts; unchanged historical labels
and source/evidence-only edits remain compatible. This manual path does not add
the stricter operator-mode requirement for per-label evidence.
