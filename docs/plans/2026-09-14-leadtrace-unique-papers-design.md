# LeadTrace Unique Papers Design

## Goal

Synchronize LeadTrace with the reorganized `source_pdfs/volume67 issue*` and
`source_pdfs/volume68 issue*` layout, and reduce the article catalog from 672
paper rows to the 648 unique PDF files without losing scientific records.

## Canonical identity

PDF filename is the grouping key because all 672 legacy rows map uniquely by
filename to one of the 648 current PDFs. For each 24-row duplicate pair, keep
the legacy paper ID whose registered PDF SHA-256 matches the current PDF. This
preserves the identity already associated with the surviving bytes. If neither
or both legacy assets match, stop and report the group instead of guessing.

## Source migration

Update `01_manifest/all_volume67_papers.csv` to contain exactly one row per
current PDF. Set `source_folder`, `source_pdf`, and `file_size_bytes` from the
current volume/issue path and file. Replace every reference to a removed paper
ID in the authoritative baseline fact files with its canonical paper ID. Reject
the migration if a file would acquire duplicate semantic records after the
replacement.

Regenerate the committed source manifest only after the scientific aggregate
and reference checks pass. The resulting manifest records the new paths,
sizes, and SHA-256 values.

## Database and release behavior

Do not mutate the published release or its immutable asset registrations in
place. Apply the reconciled baseline as a new import batch, producing new
source assets and a new release candidate. Validate and publish the candidate
through the existing release workflow. The prior release remains historical.

The new current release must expose 648 papers and 648 verified article PDF
links. Every protected PDF must resolve from a new `volume67 issue*` or
`volume68 issue*` storage key and pass byte-size, MIME, and SHA-256 checks.

## Safety and verification

Before changing source facts, create a recoverable backup of the affected
baseline files and database. Generate an explicit 24-entry old-to-canonical ID
mapping and a migration report. Run source reconciliation before any database
write. Abort on missing files, ambiguous filenames, dangling paper references,
duplicate semantic records, count drift outside the approved change, or asset
integrity failure.

Expected terminal facts are 648 paper rows, 648 unique filenames, no legacy
case-directory paths, no references to removed paper IDs, and a clean source
manifest verification.
