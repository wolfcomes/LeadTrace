# Supplement missing article metadata in a pending submission

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
4. The service accepts only missing article metadata. It verifies that the live
   science and bibliography still match the frozen submission. It uses the
   existing request-changes decision to close the old submission, then creates
   a new pending submission attributed to Admin. The previous snapshot and hash
   remain unchanged. The new bibliography section is pending, and the submission
   note explicitly says the new information is not confirmed by the Reviewer.
   Compound/Lineage viewing receipts remain valid for unchanged scientific data.
5. Verify original submission hashes, unaffected scientific tables, the unchanged
   pending queue count, Admin change provenance, new metadata in the comparison,
   and the audit chain before reopening writes. The replacement compares with
   the preceding frozen submission; earlier Reviewer changes remain in its
   original submission and complete history. No publication is created.

An identical request replays its existing replacement. A stale baseline,
non-Admin actor, non-metadata field, or attempt to replace a populated field is
rejected. Let any exception roll back the complete transaction. Do not change
versions, snapshots, assignments or confirmations to force an operation through.
Different follow-up corrections require fresh inspection and a separately
authorized operation; this service deliberately supports additive supplements.
