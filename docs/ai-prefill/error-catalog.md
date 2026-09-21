# AI Prefill Error Catalog v1

| Code or status | Meaning | Next action |
| --- | --- | --- |
| `INPUT_NOT_FOUND` | A local JSON or output path does not exist. | Check the path and rerun the command. |
| `INVALID_INPUT` | JSON or CandidateEnvelope validation failed. | Fix the reported field; do not edit the artifact after import. |
| `ARTIFACT_ROOT_REQUIRED` | Candidate import has no managed artifact root. | Supply an experiment root owned by the operator. |
| `COMPARE_INPUT_REQUIRED` | Candidate compare received only one candidate. | Provide both candidate JSON files. |
| `INVENTORY_REQUIRED` | Compound coverage check has no source inventory. | Supply `candidate coverage ... --inventory ...` with a reviewed source-based label list. |
| `HASH_MISMATCH` | Declared hashes do not match canonical content. | Remove stale hashes and let the receiver recompute them. |
| `SOURCE_DRIFT` | Candidate source identity differs from the selected PDF. | Recreate the candidate from the exact authorized source. |
| `PAGE_OUT_OF_RANGE` | A page locator is outside the source PDF. | Correct the page or record an omission. |
| `BBOX_INVALID` | A bounding box is not a positive normalized rectangle. | Re-measure the locator in PDF coordinates. |
| `STRUCTURE_REPRESENTATION` | A compound has both or neither structure representation. | Keep exactly one valid SMILES or Molfile. |
| `STRUCTURE_INVALID` | RDKit could not parse the structure. | Recheck atoms, bonds, charge, and stereochemistry. |
| `ACTIVITY_EVIDENCE_MISSING` | An activity points to an unknown Evidence ref. | Add the referenced Evidence or remove the invalid activity. |
| `ACTIVITY_WITHOUT_EVIDENCE` | An activity has no supporting Evidence link. | Review the paper and add a link, or record an omission. |
| `EVIDENCE_LOCATOR_ONLY` | Visual Evidence has no extracted quote. | Inspect the page manually in Preview. |
| `PREVIEW_REQUEST_TOO_LARGE` (HTTP 413) | Preview write body exceeds 2 MiB, including streamed/chunked bytes. | Reduce the payload; do not falsify Content-Length. |
| HTTP 422, 5000 scientific objects | Candidate object limit includes each Compound/Structure and nested lineage members/edges. | Split/reduce the proposed extraction while preserving references. |
| `OUTPUT_EXISTS` | CLI output path is already present. | Preserve it and select an unused path; immutable artifacts can be resumed with the same IDs and content. |
| `EVALUATION_IDENTITY_MISMATCH` | Feedback hashes, report, application or versions differ from the selected Workspace. | Record a new evaluation from the actual current Workspace. |
| `EVALUATION_SNAPSHOT_MISMATCH` | Scientific snapshot changed after feedback. | Re-review and record feedback for the current version before export. |
| `PREVIEW_OPERATION_FAILED` | Native lifecycle identity/resource checks or runtime operation failed. | Inspect the protected profile and registry phase; do not override unknown resources. |
| `EDGE_WITHOUT_SUPPORTING_EVIDENCE` | AI-proposed Edge has no supporting Evidence link; this does not block Preview apply. | Review the structural/SAR reasoning and relationship; do not invent a text quote. |
| `needs_review` | Technically writable, with a quality or human-review issue. | Keep the report and inspect the referenced PDF region. |
| `invalid` | A technical error prevents Preview application. | Correct the candidate and validate again. |

CLI exit codes are `0` for valid or `needs_review`, `2` for contract/input
errors, `4` for a validation report with technical errors, and `5` for an
unexpected execution failure.

`candidate coverage` also exits `4` for missing required compound labels or
ambiguous matches; its status is `incomplete`. A successful label check is
`complete_for_declared_scope`, with exclusions and extras listed explicitly.
Source drift and invalid inventory return `INVALID_INPUT` / exit `2`.

Scientific mistakes can pass these technical checks. See the
[DeepSeek quality checklist](deepseek-quality-checklist.md) for observed graph,
crop, activity-context and review-reference failures. Its `DS_*` labels are manual
review categories, not new validator/API error codes. A passing validation report
must not suppress those checks or be presented as scientific approval.
