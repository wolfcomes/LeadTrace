# AI Prefill Extraction Guide — model-neutral-v4-20261008 (CandidateEnvelope v1)

This guide describes the offline CandidateEnvelope v1 workflow. The source PDF is
read through the authorized locator in the input package. The locator is an input
permission, not provenance to copy into a candidate or send to another process.

Scientific rules in this file apply equally to routine and evaluation runs.
Operational entry points and role-specific reading lists are in
[START_HERE](START_HERE.md) and the [runbook](model-runbook.md).
The workflow is `model-neutral-v4-20261008`; CandidateEnvelope remains v1.
A frozen task bundle preserves the actual guides and hashes. Read the sections
needed for the assigned task; copying a guide is not evidence of reading it.

Confirm the source against the externally selected paper key, DOI/title, SHA-256,
byte size and page count. Read the actual PDF title/DOI; stop on mismatch rather
than relabelling a wrong article. Before first extraction, persist the observed
compound and measurement inventory. A scoped repair may reuse a verified frozen
inventory; it must not derive coverage from the current candidate alone.

Before family expansion, save one checked core record with source location,
anchor atoms, substitution positions and stereo, then map each variant's changes
to it. Derive this reference from the source before expansion, not from agreement
among generated variants. Record the expected atom/bond connectivity and ring
fusion/attachment relationships; a ring-size list alone is not an identity check.
Do this within the producer session; a core with no source-supported complete
interpretation blocks its family, not unrelated work. A defensible full candidate
with a specific remaining doubt follows the review-hint rule below. Re-read each saved final structure and compare its actual graph
and depiction to that reference and the variant's source. A common-core defect
requires checking every dependent variant; repairing one representative does not
repair the family. Do not impose a universal forbidden ring size or topology.
Every final identity still needs its substitution, chemical-form and stereo checks.
Independent review, producer self-check and technical validation remain separate.

### Ring-system verification record

For every distinct ring core, retain a compact source-derived atom/connection
record in the existing scientific-check artifact before expanding its family.
Identify heteroatoms, shared atoms/bonds for fused rings, the shared atom for a
spiro junction, and bridge endpoints/paths where applicable. Map substitution
anchors and stereo to that connectivity. Do not identify a core by a scaffold
name, ring-size list or SMILES closure digits alone; equivalent SMILES can use
different digits, and ring-basis algorithms can report different cycle sets.

Compare that source-derived record with the graph decoded from the **saved final**
SMILES/Molfile and its atom-labelled depiction. Report connectivity,
regiochemistry, stereo and chemical form separately. A successful RDKit parse,
formula match or internally consistent family is only a technical check. If the
source core cannot be established, retain uncertainty rather than declaring the
ring system verified. A supported complete structure may retain a concrete
review_hint; a known wrong structure must be repaired, not excused by that hint.

An incorrect shared core invalidates every dependent variant's identity and the
identity-dependent conclusions of its Activity/Edges. Verify each affected final
variant after repair. Reuse the checked core record and unique crops to avoid
repeated work, but still check each variant's attachment and stereo. A fresh
reviewer reconstructs the core from the source before comparing the producer's
record; unresolved disagreement remains uncertain. These are auditable scientific
records, not new CandidateEnvelope fields or claims of an automated identity gate.

### Activity evidence region identity

Verify each Activity against the compound label, target/assay, endpoint, value,
operator, unit and conditions together. For table evidence, the exact final
source/page/bbox must show the identifying row and the applicable headers and
footnote definitions, or these must be explicitly retained in the same Evidence's
source context. A crop containing the number alone does not identify the assay.
Use physical PDF page indices, not printed journal page numbers.

Check the actual final region, not an earlier rectangle. Reusing a table region
is valid only when it supports every linked Activity; matching page numbers or
compound labels alone is insufficient. With the current single-evidence Activity
contract, do not invent arrays of evidence IDs: widen a same-page region when
appropriate and preserve additional page/footnote context explicitly; if it cannot
be represented faithfully, report the limitation. Distinguish a wrong Evidence
association, wrong locator, incomplete crop and incorrect measurement separately.
After changing a locator, recheck all Activities sharing that Evidence.

## Compound catalogue scope

The default catalogue covers every source-identifiable numbered or labelled
compound with a defined structure in the available article and supplied SI:
starting materials, intermediates, protected forms and final products, whether
or not assayed and regardless of section. Named assay controls/reference ligands
also belong; classify their actual source role, not name alone. Pure background
citations are not automatically assay controls. Record the location and role for
any exclusion. Shared core plus unambiguous R groups defines a complete structure;
a separate drawing is not required.

Build the inventory from observed labels, including alphanumeric and stereo
suffixes, never an assumed continuous number range. A numbering gap triggers
source checking. Deduplicate repeated occurrences and source-supported aliases
of the same identity; keep distinct stereoisomers and chemical forms distinct.
Do not merge salts, protected forms or free bases merely because labels overlap.
Ordinary unnumbered reagents/solvents are conditions, not automatic Compounds.
A generic scaffold, variable group or open-attachment linker fragment is not a
complete chemical identity. Record observed excluded items and why they are
ineligible; do not turn them into guessed complete molecules. This differs from
an identifiable complete compound whose structure remains unresolved.

Eligible identities for which no complete structure can be found or reasonably
reconstructed stay required in the source inventory and absent from candidate
compounds, with known measurements in existing unresolved-items/omissions.
The required structure never permits placeholder or unsupported guessed SMILES.
No drawing, missing SI, no Activity or Methods-only/route-local status justifies
excluding a real control or labelled compound. An otherwise eligible identity can
be excluded only by explicit user scope; record the authorization and reason.
Do not silently treat an externally reconstructed structure as source-verified.

Always report required-scope coverage alongside `all_inventory_coverage` from
the coverage CLI, including excluded/missing/ambiguous labels. The latter covers
all inventory entries, not an independently proven exhaustive paper census.
Compound, Activity, SAR and synthesis coverage have separate denominators; adding
a Compound does not justify inventing an Activity or Edge.

## Source-supported inference and simple review hints

A Compound needs a complete structure supported by the paper: a direct drawing,
a shared core plus R-group definitions, or a reasonable reconstruction from source
reaction relationships. A separate individual drawing or unique proof is not
required for a draft candidate when the evidence supports a defensible complete
graph. Inspect that graph, chemical form and stereochemistry as usual.

When the retained candidate has a specific remaining assumption, uncertainty or
source conflict, set its optional **review_hint** to one short explanation of
**basis + doubt**, with a source location when available (maximum 1000 characters).
The same optional field is available on Compound (including structure doubts),
Activity and LineageEdge. The UI renders one **⚠**, meaning **需核对**; the text
itself needs no symbol, confidence percentage or risk level. Use only actual doubts,
not generic warnings on every item. Blank/absent text means no hint, not approval.

Series order may support a proposed individual pairing when a shared core,
substituent definitions and a compatible family reaction support that mapping.
State the pairing assumption in review_hint. Number order or a collective range
alone is insufficient: if no complete graph is defensibly reconstructable, omit
the Compound; never insert an empty identity card, fake SMILES, or dangling
Activity/Edge references. Preserve the missing identity/observations in the
existing inventory and omissions so the coverage gap remains visible.

A hint cannot legitimize an invalid graph, known wrong connectivity, contradicted
pairing or fabricated observation. Correct known errors first; omit an unsupported
record when no defensible candidate remains. Conflicting source values may retain
a justified value with a hint identifying the competing location/value; do not
average or invent a compromise. A warning does not make an uncertain item correct
in a scientific audit, and technical acceptance does not prove its source basis.

Use the existing edit/review actions. Resolve the doubt, correct the record if
needed, then explicitly clear the hint. Confirming a structure or edge does not
automatically clear it; unresolved hints persist into submission/publication.
No new review states, identity placeholders or issue-management objects are added.
CandidateEnvelope/payload stay v1; absent hints preserve legacy serialization and
hashes. Freeze the actual updated schema and guides in every new task bundle.

## Workflow

1. Read the input package and confirm `target.paper_key`, source SHA-256, byte size,
   page count, guide version, parent candidate, and every feedback ID.
   For first extraction build a source compound inventory BEFORE candidate access;
   for repair verify the existing frozen inventory and expand any missing scope.
   Enumerate actual labels in every SAR/activity table, structure figure,
   synthetic scheme and experimental heading. Distinguish assayed compounds,
   references, intermediates and starting materials. Do not restrict extraction
   to compounds already in a legacy candidate or only to compounds with Edges.
   Count repeated controls once; retain stereoisomers as distinct identities.
   Record required labels and every exclusion for the independent reviewer.
2. Extract compounds, structures, lineages, Evidence, and activities from the PDF.
   Existing CSVs are partial inputs, not proof that a section is absent. Inspect
   main-article assay/SAR tables even when CSV activity rows are empty. Render
   image-only tables and check headers, compound rows, footnotes and units.
3. Use review_hint for a supported retained item with a concrete doubt; record an
   omission and reason for an unsupported or unrepresentable item. An empty section means “not extracted yet”, not “the paper has no
   such information”.
4. Validate structure identity with the displayed compound label, stereochemistry,
   charge, and the structure drawing. Use exactly one of SMILES or Molfile for each
   compound. RDKit parsing and agreement with an HRMS molecular formula do not
   prove atom connectivity. Avoid interpolating SMILES fragments with overlapping
   open ring-closure digits: use atom/bond fragment assembly or disjoint ring
   labels. Compare final depictions and expected core/ring sizes against original
   drawings, including regioisomers and stereochemistry; do not merely canonicalize
   a graph that may already be wrong.
   Render and inspect each unique FINAL (source hash, page, bbox), not a nearby
   crop or full-page preview. Record the labels and core/R-group definitions it
   actually contains; shared crops may be checked once and mapped to all dependent
   compounds. Each Compound's own locator set must combine its core, identifying
   row and every substituent definition, including table endpoints/footnotes.
   Label shared regions honestly. A generic range or number order alone cannot
   identify variants; source-supported family mapping with a remaining pairing
   assumption follows the review-hint rule above. Missing reference
   drawings stay explicitly absent; RDKit depictions are not original evidence.
5. Set each new Lineage's `lineage_type` explicitly to `sar` or `synthesis`.
   `unspecified` is for unclassified legacy/uncertain records, not a shortcut for
   mixing SAR and synthesis in one graph. Build separate records for the two
   narratives, sharing Compound IDs only where identity and chemical form match.
   The same pair may have both a synthesis edge and an independently justified
   SAR comparison; a reaction alone neither establishes nor forbids that comparison.
   Include eligible labelled precursors and intermediates as Compound entities,
   with genuine structures and source locators even when they have no Activity.
   Keep additional route context and unresolved steps in route-details; do not
   use route-local status to exclude an eligible identity. A reaction with two
   substrates is one preparation event: preserve both substrates and conditions.
   If represented by binary edges, identify their shared reaction and co-reactant
   context; do not count them as separate preparations or invent direct steps.
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
   Reconcile the source Edge inventory after every compound-coverage repair.
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
   This is a source review requirement; `candidate coverage --inventory` currently
   measures compound labels only and does not certify Edge completeness.
   Apply the grouping, role and participation rules below as part of this inventory.
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
   Reconcile observations from tables AND abstract/Results/PK/kinetics/figure
   captions. Route each to Activity, evidence/context, calculated property,
   duplicate report, source conflict or unresolved graph; count these separately.
   Crystallographic resolution and computed properties are not automatically
   missing Activity rows. Keep dose/route/time as conditions, not potency endpoints.
   When a threshold explicitly applies to several named targets, record each
   target separately without extending it to unreported targets. Keep repeated
   table reports identifiable by source context; they are not necessarily
   independent experiments. Preserve pIC50/pEC50 as reported metrics.
9. Write the CandidateEnvelope JSON, then run `candidate validate`. A `needs_review`
   report can be previewed; an `invalid` report must be corrected before apply.
10. Run `candidate coverage candidate.json --inventory compound-inventory.json`
    against the frozen source inventory, stating its actual review status. Missing required labels
    or ambiguous alias matches exit 4, even when omissions explain the gap.
    Correct missing compounds or explicitly report an incomplete delivery; never
    claim paper completeness from successful schema validation or matching the
    original candidate count. This is an operator preflight, not an API-enforced
    rule. A label match does not prove a correct structure or complete activities.

## Lineage grouping, roles and participation

These rules apply to extraction, revision and review. A Lineage is an explained
relationship group, not a container for every compound of one paper or type.

### Build source records before assembling the graph

Save the source preparation/comparison units first, then map them to candidate
edges and groups. A preparation record identifies substrate/product labels,
co-reactants, direct or multistep semantics, conditions and precise source location.
A comparison record identifies the baseline, structural differences, assay context
and author-stated versus AI-proposed interpretation. Map every final edge to its
record; also list source relationships omitted or unresolved in the graph. A count
of drawn arrows, preparation units, branch expansions and binary edges describes
different populations; name the counting unit instead of forcing equal counts.

Collective label ranges alone do not establish individual R-group assignments or
precursor/product pairings. Apply the source-supported inference rule above:
a defensible complete reconstruction can be retained with a specific review_hint;
an unsupported guess cannot. Preserve the required identity and known observations
in existing unresolved records when no complete structure can be supported. For an existing workspace, surface this as a blocking proposed
reconciliation; do not silently delete records or overwrite human edits. A named
structure must retain its actual identity basis and unresolved attributes; a
name-derived structure is not a visually confirmed source drawing.

A condensed route must enumerate its actual steps and known intermediate labels;
calling an edge multistep does not excuse a missing deprotection or unrecorded
collective transition. If a new Compound is added, revisit its known observations,
locators and both relationship types, even during a lineage-only repair.

### Group by meaning, then inspect connectivity

- Give each group a specific route or comparison-axis label and explain its scope.
  Prefer a connected group when supported. Report weakly connected components
  (ignore arrow direction for this count) and members with no incident edges.
  A disconnected group requires an explicit reason and review disposition; it is
  not automatically scientifically wrong. Do not create edges just to connect it.
- Connectivity alone does not determine grouping. A shared reagent can connect
  otherwise distinct series; several routes may legitimately share one Compound.
  Conversely, retain meaningful upstream/downstream branches together even when
  they cross Scheme or article-section boundaries. Avoid both unexplained large
  containers and arbitrary fragmentation. There is no fixed node-count threshold.
- Synthesis may have several starting substrates and convergent paths; do not
  force it into a single-root tree. Preserve preparation IDs, co-reactants,
  conditions, evidence and direct/multistep semantics through any regrouping.
  Do not duplicate the same scientific edge merely to fill several views; explain
  cross-group participation and links in descriptions where useful.
- SAR may be baseline comparisons, several related comparison axes or supported
  design evolution. State which interpretation applies. Distinguish single-variable,
  multivariable and cross-study comparisons. Do not remove a justified comparison
  merely to obtain a tree; flag cycles for interpretation rather than silently
  deleting edges. Never restore a rejected edge based on numbering or appearance.

### Separate graph position from scientific role

| Context | Meaning and current representation |
|---|---|
| Synthesis `root` | No incoming edge and at least one outgoing edge in this group; may be a co-reactant rather than the originating lead. |
| Synthesis `intermediate` | Both incoming and outgoing edges in this group. |
| Synthesis `terminal` | At least one incoming edge and no outgoing edge in this group; not proof of an absolute route endpoint or selected lead. |
| Isolated member | No incident edges: do not call it root or terminal. Use `unspecified` with an explanation if retained pending review, or remove only the unjustified membership while preserving the Compound and other memberships. |
| SAR baseline / comparison entry | A documented baseline may be `root`; a graph entry inferred only from direction must be described as such. Other members may remain `unspecified` with their comparison role explained. Do not impose synthesis roles on a parallel comparison. |

Roles are scoped to a particular Lineage. The same Compound can be a synthesis
intermediate and a SAR baseline. Check roles again after adding/deleting/moving
edges. Surface conflicts with existing human annotations for reconciliation;
do not silently overwrite them using degree counts.

### Article-level starting points and prioritized compounds

Use optional payload compound_highlights for source-backed study_start and
paper_selected assertions. These are orthogonal to Lineage roles, not a fourth
member role and not the biological target. A study starting point is the hit/lead
from which the authors pursue this work, not every synthetic reagent. A
paper-prioritized compound is explicitly selected or advanced by the authors on
combined evidence, not every terminal or the best number in one assay.

Each annotation requires a unique ref, compound_ref, evidence_ref, role, nonblank
scope (whole paper or named study/series), and rationale. Optional review_hint
records ambiguity. The Compound and Evidence must be present in the same payload.
Evidence must locate the author statement using actual PDF page and quotation or
region; rationale explains the selection and retains its limits. Multiple starts,
multiple prioritized compounds, and both roles on one Compound are allowed;
do not duplicate the same compound/role/scope. AI cannot set review_status: apply
always creates draft annotations, requiring an explicit human disposition later.

Read relevant Introduction/Results/Discussion/Conclusion statements as part of the
existing source pass. Do not infer these identities from label order, graph degree,
route endpoint or single-assay potency. Uncertain source-backed proposals remain
clearly flagged; an unsupported guess should stay out of annotations. Record
unreviewed, reviewed-but-no-explicit-selection-found, and explicitly-no-selection
outcomes in the compound_scope self-review details / unresolved handoff, with
locations. An absent/empty list means unrecorded, not proven absent. Legacy
candidates without this optional list remain valid and keep their hashes; new
runs must address the coverage question. Do not scientifically backfill existing
workspaces from graph topology. Self-check and fresh independent review verify
statement, scope, Compound structure identity and Evidence linkage together.

#### Role decision record (mandatory)

Before creating or repairing a highlight, build a small source-side role matrix
for each relevant series. It must record: (a) the exact author wording and PDF
location, (b) the study/series scope, (c) every compound named in that wording,
and (d) whether the wording is an explicit role statement, supporting context,
or only an observation. Search the Abstract, Introduction/Design, Results/SAR,
and Discussion/Conclusion before comparing the draft row. A table, scheme, or
figure can be the linked Evidence only when it supports the role identity, not
merely the existence, synthesis, PK, or one assay of the Compound.

The following are prohibited shortcuts and require an explicit source statement
to override them: lowest or first compound number, first row of a table or
scheme, last synthetic product, terminal graph degree, appearance in an in-vivo
or PK experiment, highest potency in one assay, or a compound mentioned in a
highlighted crop without selection language. For example, a strong CA-II value
does not establish a dual CA/MAO-B paper-selected compound when the second target
is inactive or the compound is absent from the paper's follow-up panel.

Treat the two roles independently. `study_start` may contain both a literature
hit and the paper's internal lead when the article uses both scopes; state the
scope in `scope` and do not collapse them into one label. `paper_selected` may
contain several compounds when the authors name a set of leads, candidates, or
parallel endpoints. Add one highlight per compound/role/scope, or leave the
role unresolved when the source does not justify a single choice. Never replace
a multi-compound conclusion with the strongest-looking member.

When reviewing an existing row, use one of these dispositions in the audit
record: `role_identity_error` (the compound conflicts with the source),
`role_incomplete_or_ambiguous` (the compound is supported but a named set was
collapsed to one row), `evidence_linkage_error` (the compound/role is supported
but the linked Evidence does not prove that role), or `no_issue_found`. A
`evidence_linkage_error` is repaired by replacing Evidence, not by deleting a
correct Compound role. Keep all repaired rows `draft` until a human reviewer
decides their final state.

### Account for participation without inventing a lineage

For every Compound, review SAR and synthesis participation separately. Distinguish
membership with edges, an isolated member, and absence from all groups of that
type. Report global nonmembers separately. For each missing/isolated participation,
record a reason, review status and supporting source context or explicit lack of
verification. Examples: reference/control, background design reference,
precursor-only for SAR purposes, source does not establish a relation, or extraction
not yet checked. “Not reported” and “not yet extracted” must not be conflated.

Place necessary explanations in the Compound description and relevant Lineage
description so they reach Preview, as well as the review notes. Preserve existing
descriptions when appending. A reference collection can aid browsing but is not
automatically a scientific lineage. Absence of activity, text quotation or lineage
membership does not remove an eligible Compound from the catalogue.

### Delivery checks and implementation boundary

In review notes, bind the checks to the final candidate hash and list, per group:
type, scope, member/edge counts, component count, isolated labels, role conflicts
and disposition. Separately list participation reasons, paper-selection claims
or unknowns, rejected relations and remaining scientific gaps. `candidate self-check`
now reports graph components, isolated members, cycles, synthesis-role conflicts and
per-type nonparticipation as review diagnostics; it does not approve their scientific
meaning, invent reasons, split groups or add edges. Source interpretation remains a
producer/independent-review task; `candidate coverage` checks labels only. Use existing `sar_reasoning` and
`synthesis_paths` self-review details; keep `checked_edge_refs` to real edge refs.

When regrouping an existing Preview, use the versioned Reviewer workflow, preserve
unaffected content and evidence, record any recreated edge IDs and verify before/
after semantics. Check graph display separately from scientific correctness:
single-group rendering, large-graph readability and repeated switching are distinct
checks. A fresh-page pass does not resolve a repeated-switch crash. Keep runtime
observations in the run handoff, not as universal extraction rules.

## High-risk structure and table checkpoints

The core/variant checkpoint above must resolve attachment atoms and substitution
positions: formula/string agreement cannot distinguish regioisomers. Keep unresolved
families blocked; use explicit atom/bond joins instead of colliding ring digits.

For each table first save a column/row map containing printed headers, units,
all groups including vehicle/model controls, doses and footnotes. Compare first,
middle, last and control rows on the rendered table before conversion. Do not
remove a model-control row then zip the remaining labels to unchanged values.
Keep raw tokens plus row/column coordinates: `L929` is a cell-line label, not a
number such as `1.929`. Check APD30/APD90/APA/Vmax column identities and distinguish
absolute units from delta-percent units; match the dose actually printed, never
synthesize a missing 20 mg/kg row from a 10 mg/kg value.

Inventory every main table separately even when earlier tables share a scaffold.
One table’s coverage does not imply another’s. Include reported selectivity
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
approval. The optional [quality sidecar](templates/quality-record.json)
records these checks outside CandidateEnvelope; it is not a built-in validator
or formal Evaluation.

## Internal reference safety

Entity `ref` values must not contain `/` (receipt path separator). Use identifiers such as `compound:1`, `lineage:sar`, `edge:1-to-2`; printed compound labels and descriptions retain their original punctuation. Candidate validation rejects unsafe refs before Preview apply.

### 可选文章元数据：Abstract 与 PDB

`bibliography.abstract` 保存原文摘要，`abstract_source` 记录页码/位置；不把模型总结当原文摘要。未找到时省略，不能为填满字段编造。`bibliography.pdb_references` 是提及记录数组，每项包含 `pdb_id`、`usage`（`this_work` / `cited_structure` / `unknown`），以及可选的 `source_page`、`source_context`、`compound_label`、`review_hint`。PDF 页码从 1 开始，不能超过原文件页数。保留用途和来源上下文；只有来源明确配对时才填写 compound_label，不凭 docking 常识猜配体对应。无法确定用途用 unknown 并简要写核对提示。

PDB ID 接受传统四字符（例如 1ABC）和扩展格式（例如 pdb_00001abc）；三字符配体代码（ATP 等）、DOI、UniProt ID 不属于此字段。同一个 PDB ID 在不同上下文中可多次出现，不能据此把引用结构认作本文新解析结构。不要查询外部结构反推论文未报告的编号。旧候选可不含这些字段；对既有文章补录仍遵守版本化修改及人工编辑保护。
