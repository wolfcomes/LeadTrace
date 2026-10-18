# Complete source catalog and manual removal

User scope: import all local article PDFs to production and add manual removal preserving PDFs.

Design: recurse volume/issue folders (including ok/OK); exclude historical extraction reference-library PDFs. Bibliographic metadata only; deduplicate DOI, hash and source key against all rows including removal tombstones. New papers remain unassigned without AI jobs. Never overwrite existing scientific records or restore removed papers. Freeze a deterministic manifest and verify original file identity before transactional audited insert; rehearse in isolated restored DB and verify old records remain unchanged.

UI: reuse existing DELETE paper endpoint. Add removal on catalog and article management; modal shows identity, reason, typed paper key, PDF retention and ordinary-access removal, reads fresh expected workspace/task versions. Reject active jobs or stale identities with clear messages and require renewed confirmation after refresh. Reload catalog after success and fix last-page empty result.

Validation: meaningful dialog/API tests (confirmation, active job, stale versions, failure); typecheck/build; existing removal DB regression serially on disposable _test DB; read-only live browser check, no real removals. Fresh verified backup before import. Release isolated source commit only; preserve preexisting root edits.
