# Supplement article metadata in a pending submission

Use this operation only for an explicitly authorized administrative supplement.
It is an operator service, not a Reviewer impersonation or a scientific approval.
The normal Reviewer editor remains the path for editing an open draft.

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
5. Verify original submission hashes, unaffected scientific tables, the unchanged
   pending queue count, Admin change provenance, new metadata in the comparison,
   and the audit chain before reopening writes. Consecutive replacements retain
   the originating Reviewer round's comparison baseline, so Reviewer edits and
   subsequent supplements remain visible together with their actual attribution.
   Verify that `reviewer_diff` matches the originating round, routine confirmations
   stay folded, and the original Reviewer note is displayed separately with its
   immutable submission link. New metadata remains unconfirmed. A genuine Reviewer
   resubmission begins a new round; an invalid supplement link must show a warning.
   No publication is created.

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
submission remains immutable, and its replacement is pending/unconfirmed.
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
