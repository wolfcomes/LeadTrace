# AI Prefill Extraction Guide — deepseek-supervised-v2 (CandidateEnvelope v1)

This guide describes the offline CandidateEnvelope v1 workflow. The source PDF is
read through the authorized locator in the input package. The locator is an input
permission, not provenance to copy into a candidate or send to another process.

For supervised DeepSeek runs, also read the
[supervised runbook](deepseek-supervised-runbook.md),
[quality checklist](deepseek-quality-checklist.md), and
[stage prompt](prompts/deepseek-task.md). The run policy is
`deepseek-supervised-v2`; CandidateEnvelope remains v1. The operator must copy the
guides into the actual task input and record their versions/hashes. Adding these
files to the repository does not automatically change harness prompts.

Use a survey/representative-core checkpoint before expanding a whole series.
Every distinct core and high-risk ring/linker/stereo variant needs a source
comparison at that checkpoint. Still compare every final labelled structure with
the source after expansion. Self-reported checks and technical validation are
separate from the supervisor's independent scientific checks.

## Required delivery gates (v2)

These are operator gates, not new API capabilities. Use the
[quality audit protocol](quality-audit-protocol.md) and
[independent audit prompt](prompts/deepseek-audit.md).

- Bind the task to an independently selected manifest/catalogue entry by paper
  key, expected DOI/title, source SHA-256, byte size and PDF page count. Matching
  candidate to input is insufficient if the input selected the wrong article.
  Read the actual PDF title/DOI in the harness. On mismatch, stop and report;
  never relabel the candidate to hide a different source. Preserve the failed
  package. Codex may check metadata without reading the article when instructed.
- `compound_label` is the EXACT printed identifier, not identifier plus a name.
  Put explanations in `display_name`/`description`. Keep `1a`, `R-58`, `S-58`,
  primes and named unnumbered controls; do not globally strip to digits. A pure
  number rule was specific to the 41-compound 005 label repair.
- Before candidate access, persist `compound-inventory.json` in the existing
  CompoundInventory v1 format, with page/table locators and required/excluded
  scope. Record its hash and provenance. A source-informed uncertain identity
  stays in the denominator; unresolved structure does not erase a compound.
  The current payload requires a structure: report such coverage as incomplete
  and preserve the label/measurements in a sidecar, never use placeholder SMILES.
- Deliver `quality-record.json` plus row-level source comparison records. Counts,
  RDKit parsing, locator existence and model assertions are not scientific
  accuracy. Unknown denominators or unchecked visuals must stay unknown.
- Treat SAR and synthesis as separate inventories/metrics. Missing text evidence
  does not invalidate a reasoned AI edge. Methods-only intermediates stay in
  route details with source support unless main-narrative scope includes them.
- Copy the exact guide bundle into each job, record each file hash and prompt
  version, and verify prompt references before launch. Old job-local guides do
  not become current when repository docs change. Do not silently rewrite past
  job inputs or their hashes.

## Workflow

1. Read the input package and confirm `target.paper_key`, source SHA-256, byte size,
   page count, guide version, parent candidate, and every feedback ID.
   Build a separate source compound inventory BEFORE using existing candidates.
   Enumerate actual labels in every SAR/activity table, structure figure,
   synthetic scheme and experimental heading. Distinguish assayed compounds,
   references, intermediates and starting materials. Do not restrict extraction
   to compounds already in a legacy candidate or only to compounds with Edges.
   Count repeated controls once; retain stereoisomers as distinct identities.
   The supervisor reviews required labels and explicit scope/exclusions.
2. Extract compounds, structures, lineages, Evidence, and activities from the PDF.
   Existing CSVs are partial inputs, not proof that a section is absent. Inspect
   main-article assay/SAR tables even when CSV activity rows are empty. Render
   image-only tables and check headers, compound rows, footnotes and units.
3. Record an omission with a reason whenever the paper leaves a field uncertain or
   unsupported. An empty section means “not extracted yet”, not “the paper has no
   such information”.
4. Validate structure identity with the displayed compound label, stereochemistry,
   charge, and the structure drawing. Use exactly one of SMILES or Molfile for each
   compound. RDKit parsing and agreement with an HRMS molecular formula do not
   prove atom connectivity. Avoid interpolating SMILES fragments with overlapping
   open ring-closure digits: use atom/bond fragment assembly or disjoint ring
   labels. Compare final depictions and expected core/ring sizes against original
   drawings, including regioisomers and stereochemistry; do not merely canonicalize
   a graph that may already be wrong.
   Populate `structure_locators` with original PDF page/bbox regions, visually
   checking that the complete drawing and its identifying label are inside the
   crop. Include substituent definitions for shared scaffolds and explicitly say
   in `label`/`source_context` that these are not independent complete drawings.
   The review UI displays each compound's own locators only. For every compound,
   attach its shared core AND its substituent definitions/identifying row (as
   separate original crops or an encompassing table region). Linking the core to
   only one representative compound leaves the remaining structures incomplete.
   Explicitly record absence when the PDF has no drawing for a reference control.
   A generated RDKit depiction is not an original PDF crop.
5. Set each new Lineage's `lineage_type` explicitly to `sar` or `synthesis`.
   `unspecified` is for unclassified legacy/uncertain records, not a shortcut for
   mixing SAR and synthesis in one graph. Build separate records for the two
   narratives, sharing Compound IDs only where identity and chemical form match.
   For the current main-narrative/SAR catalogue scope, keep Methods-only
   intermediates, free-base preparations and salt conversions in synthesis route
   descriptions with exact labels, names and source evidence; do not create global
   Compound rows for these solely to complete a route. Explicitly discussed
   intermediates in the main narrative may remain in the Compound catalogue even
   without Activity. If a future task requires every intermediate as a graph node,
   use route-local entities or agree an expanded scope explicitly.
   Review Results/Synthesis, Methods and SI together; article section is provenance,
   not the relationship type. A condensed edge must be labelled a multi-step route
   summary and enumerate omitted steps/forms; never imply a single reaction.
   Keep synthesis relationships separate from optimization relationships. A
   reaction or preparation step is not evidence that a compound is more potent;
   record the relationship only when the paper supports that interpretation.
   An Edge may be proposed from AI interpretation of structures, series design,
   figures, or SAR even when there is no text quotation. Record the reasoning and
   source context in `modification_summary`, clearly labelled as AI inference;
   leave `edge_evidence_links` empty if there is no actual Evidence. Never invent
   a quotation, page, or Evidence record to satisfy an Edge requirement. Unlinked
   Edges are allowed in Preview and produce a nonblocking `needs_review` item.
   AI-created Edges stay `draft`; a reviewer must confirm or mark them unresolved
   before submission. Reviewer-confirmed Edges do not require a supporting text
   Evidence. Keep explicitly rejected relations and unresolved endpoints out of
   the proposed graph.
   Perform an independent Edge inventory after every compound-coverage repair.
   Enumerate each main SAR axis and each labelled reaction arrow, then record
   endpoint labels, relationship kind, source locator, reasoning, and whether the
   relation is present, missing, or withheld with a concrete reason. A compound
   added to the catalogue is not automatically a Lineage member or Edge endpoint.
   Report compounds outside all Lineages as review candidates, not proof that
   every isolated compound needs an Edge. Separate source-stated transformations,
   AI-proposed structural/SAR comparisons, and unresolved parentage. A known SAR
   baseline is not automatically the direct synthetic precursor; a baseline arrow
   does not imply chronological development or an improvement in potency. Do not
   guess a parent from numbering, connect every pair, or skip named intermediates.
   Missing text quotation alone is never an exclusion reason for a well-reasoned
   candidate. Preserve source label conflicts and check the labelled drawings.
   This is a supervisor audit; `candidate coverage --inventory` currently
   measures compound labels only and does not certify Edge completeness.
6. For every text or table Evidence, preserve page number, meaningful punctuation,
   numeric values, units, comparison operators, and Unicode symbols. Do not turn a
   range, `<`, `>`, decimal point, or minus sign into a different value.
7. For schemes, images, and tables without stable text extraction, record the page
   and normalized bounding box. This is valid for Preview but remains a human
   review item.
8. Link activities to Evidence when the source supports the measurement. Do not
   use `0` for a value that is missing, qualitative, or reported as a range.
   Preserve each assay/target/endpoint separately. Keep original units, reported
   precision, conditions, raw cells and SD in `context` when no dedicated field
   exists. For table transcriptions, use table Evidence with page/bbox and a
   clearly labelled caption; leave `quoted_text` empty unless it is an actual
   source quote. Report which compounds have no located measurement and which
   tables were covered. Do not reject a negative measured inhibition percentage
   merely because it is negative.
   Keep dose/route/time as assay conditions, not standalone potency endpoints.
   When a threshold explicitly applies to several named targets, record each
   target separately without extending it to unreported targets. Keep repeated
   table reports identifiable by source context; they are not necessarily
   independent experiments. Preserve pIC50/pEC50 as reported metrics.
9. Write the CandidateEnvelope JSON, then run `candidate validate`. A `needs_review`
   report can be previewed; an `invalid` report must be corrected before apply.
10. Run `candidate coverage candidate.json --inventory compound-inventory.json`
    against the independently reviewed source inventory. Missing required labels
    or ambiguous alias matches exit 4, even when omissions explain the gap.
    Correct missing compounds or explicitly report an incomplete delivery; never
    claim paper completeness from successful schema validation or matching the
    original candidate count. This is an operator preflight, not an API-enforced
    rule. A label match does not prove a correct structure or complete activities.

## Failure-specific checkpoints from the quality audit

Before series expansion, require the supervisor handoff artifact for one accepted
core per family. Inspect the molecule GRAPH for the intended lactone/piperazine
connectivity; if ring digits are reused while a core ring is open, stop expansion.
Use explicit atom/bond joins with verified attachment indices. 013 repeated the
same failure previously seen in 007/009: a warning paragraph without a completed
checkpoint did not prevent it. Record numbered indole atoms when mapping 5-F vs
6-F or other regioisomers (010); string similarity and formula cannot decide.

For each table first save a column/row map containing printed headers, units,
all groups including vehicle/model controls, doses and footnotes. Compare first,
middle, last and control rows on the rendered table before conversion. Do not
remove a model-control row then zip the remaining labels to unchanged values.
Keep raw tokens plus row/column coordinates: `L929` is a cell-line label, not a
number such as `1.929`. Check APD30/APD90/APA/Vmax column identities and distinguish
absolute units from delta-percent units; match the dose actually printed, never
synthesize a missing 20 mg/kg row from a 10 mg/kg value.

Inventory every main table separately even when earlier tables share a scaffold.
005 Table 1 coverage did not imply Table 2 coverage. Include reported selectivity
ratios/inequalities and reference controls in the source ledger; state exclusions
for calculated properties and unknown/ND/NT cells instead of silently dropping
a column. Source-reported predictions are explicitly labelled as predictions,
not measured activity. Missing source observations belong to COVERAGE metrics;
they are not erroneous rows in a candidate-row ACCURACY sample.

## Revision loop

Use `parent_candidate_id` for a revision. Include the exact evaluation IDs that
informed the revision and keep the original candidate unchanged. A second candidate
with the same source can be compared with `candidate compare`; ambiguous duplicate
refs are reported instead of being guessed away.

## Minimal commands

```text
python -m leadtrace.ops.ai_prefill doctor
python -m leadtrace.ops.ai_prefill contract export --output docs/ai-prefill/schemas/candidate-envelope-v1.json
python -m leadtrace.ops.ai_prefill candidate validate candidate.json
python -m leadtrace.ops.ai_prefill candidate compare candidate-v1.json candidate-v2.json
python -m leadtrace.ops.ai_prefill candidate import candidate.json --artifact-root /path/to/ai-prefill
```

The `doctor` command is offline by default. No command in this guide reads a
database or starts a worker.

The offline validator does not independently hash the source PDF or prove
structure identity, table completeness, or crop content. Check the actual source
file against the input identity, inspect real crops, and record scientific checks
before requesting Preview application. An exit code of 0 is not scientific
approval. The optional [quality sidecar](templates/deepseek-quality-record.json)
records these checks outside CandidateEnvelope; it is not a built-in validator
or formal Evaluation.

## Internal reference safety

Entity `ref` values must not contain `/` (receipt path separator). Use identifiers such as `compound:1`, `lineage:sar`, `edge:1-to-2`; printed compound labels and descriptions retain their original punctuation. Candidate validation rejects unsafe refs before Preview apply.
