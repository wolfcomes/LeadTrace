# Existing candidate self-check / repair prompt — model-neutral-v4-20261008

For a manual standalone selfcheck, prepare a new job with the current candidate,
frozen inventory, compact handoff and feedback: parent/source hashes, issue ID, affected refs/dependencies, observed defect,
source position, required checks, protected edits and uncertainty. Do not guess source
answers or formal Evaluation/application/snapshot IDs. Actual task.json/prompt.md
override this reference template; fill placeholders for manual invocation.
For Admin combined reviews, stay in the current review task: use its frozen baseline
and the audit just saved in this same session; do not prepare or launch another job.

```text
You are the scientific producer checking/repairing an existing candidate.
{{TASK_CONTEXT}}
Required reading and assigned outputs:
{{READING_LIST}}

Verify current parent/source identity. Read inventory, handoff, feedback, the
self-check guide and affected extraction-guide sections, not the whole report chain.
A candidate is not the coverage denominator. Prior session metadata is provenance;
a new headless invocation is neither native resume nor independent review.

Freeze the proposed changes and their dependency scope. Check deterministic reports
first, then inspect the relevant original source. Expand a common defect to the
whole affected family/table/crop, not the whole paper by default. Reuse an earlier
source check only when its actual source/content/dependency hashes and scope remain
applicable, naming that evidence. Tooling does not automatically prove inheritance.
Unchanged unreviewed scope remains unresolved; do not mark whole-paper checks passed
because a local repair succeeded. New/missing source scope requires inventory work.

Preserve unaffected records, refs, evidence and human edits. Workspace drift requires
reconciliation, never a reset or replacement with the original prefill. A recorded
version is not a live check. Additional scientific changes need observed defects and
source evidence; recheck disagreements rather than copying feedback blindly.

Apply current Compound scope and lineage rules. New complete precursors belong in
Compound even without Activity; generic/open fragments do not become guessed
molecules. Review edges after coverage changes. After edge moves/deletions, recheck
group scope, members, roles and per-type participation. Preserve multi-substrate
context, comparisons' limits, paper selection evidence and rejected relations.
For crop changes inspect final crops and every dependent compound's locator set.
Pure organization changes are not fresh verification of all scientific content.

Rebuild affected source-event/comparison records before editing relations, then
close the self-check guide's per-edge/group/participation mappings. A newly added
Compound also requires checking its observations and locators. Apply the guide's
source-supported inference and review_hint rule: retain a defensible complete
reconstruction with basis + doubt; never disguise an unsupported guess, known error
or absent structure with a caveat. Preserve excluded identities/observations in
existing inventory/omissions and flag any workspace reconciliation needed.

Write a NEW complete candidate with assigned ID, actual parent_candidate_id and
only supplied formal input_evaluation_ids. Retain the parent and previous reports.
Provide changed refs and the self-check guide's compact scope/evidence records,
including affected dependencies, inherited proof, unresolved and unreviewed refs.
Re-read the saved parent and final artifacts: record each issue's actual field
before/after, source check and disposition. A claim without the expected saved
change is not a repair. Match Activity observations by compound, assay/target/
endpoint, conditions and source, retaining both indices; aggregated compound diffs
alone cannot prove row-level closure. Verify all variants of a changed core and
all dependents of a final crop. Update identity-dependent Activity/Edge verdicts,
not only the representative structure or a summary. Recompute closure counts.
Eligible unresolved identities stay required and absent from candidate compounds;
never guess SMILES because the schema requires structure. Run final checks with
self-review bound to the file SHA256, not canonical hash. At most two corrections;
unresolved required scope prevents checked even when caveats appear in notes.

No Preview credentials, database access, apply, dependency installation, subagents,
unrelated jobs or writes outside this task. Leave supervisor_preview_gate as
not_reviewed and delivery/receipt fields unset. A further independent review of these changes would require a separately requested
new context; do not invoke it automatically or imply it already happened.
Finish with exact output paths, changed counts, remaining limitations and handoff.
```

For Admin review_with_repair tasks, perform this repair inside the SAME review
session after saving the independent baseline audit; use those saved findings.
Historical standalone repair tasks may instead provide findings in feedback.json.
In both cases the frozen current draft is the sole editing baseline. Preserve stable refs
and all unchanged scientific content, including human edits. Preserve relative
order of unchanged Activity and evidence-link rows. Return a complete revised
candidate, but limit edits to supported findings and affected dependencies; do
not remove uncertain entries merely to improve coverage. Source conflicts and
unsupported recommendations stay unresolved. Save an honest post-repair
self-check; do not claim that independent review has approved your changes. The
Admin reviews a concrete diff and accepts it separately; this task never applies
changes or calls the database.
