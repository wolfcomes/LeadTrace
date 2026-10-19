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

### Decide the scientific question and SAR graph boundaries

For each SAR graph, identify a common starting point or explicit comparison
baseline, a clear optimization theme, and source-supported relationships. State
the scientific question before choosing members and edges. A graph can contain
multiple documented baselines or convergent comparisons; this principle does not
require a single-root tree. Keep synthesis relationships in separate graphs.

| Situation | Grouping decision |
|---|---|
| One baseline and one theme, with a batch of parallel analogues | Usually keep one graph, including unsuccessful and unselected branches. |
| One root with independently meaningful optimization series, sites or scaffold branches | May split by theme; reuse the same Compound as the local root where supported. Branching alone does not require splitting. |
| A selected compound becomes the design baseline for a new exploration batch | Prefer splitting at this hub: it may be terminal in the preceding graph and root in the next. Explain the transition and cite its basis. |
| A short two/three-step progression within one theme | Usually keep together. Neither an intermediate nor a hub annotation automatically requires a new graph. |
| Extensive cross-comparisons or convergence are needed to understand the relationships | Prefer keeping the related comparisons together; retain every supported incoming edge. |

Table/Scheme boundaries, compound count, or a change of objective alone do not
decide graph boundaries. For every proposed split/merge, explain the scientific
scope and check the before/after relationship inventory. Reuse existing Compound
refs across groups rather than creating duplicate compounds. Preserve supported
relationships, unsuccessful branches, Evidence links, directions and comparison
contexts; do not duplicate the same scientific relationship just to populate
both graphs. Record unresolved or unrepresented relationships explicitly.

Each graph description should state: baseline(s), optimization theme, member
scope, relationship/evidence basis, and links to adjacent graphs via shared
compounds where applicable. Choose an edge's parent from the actual direct design
baseline or comparison in the source, not label order, similarity or potency rank.
Keep compounds without an established relationship in the catalog; do not invent
an arrow to make a complete-looking graph.

The following examples are fictional decision aids, not source evidence:

- `1 → 2/3/4`, one site and theme: one graph; retain unsuccessful `4`.
- First batch `1 → 2/3/4`, then the authors use `3` as the baseline for a new
  batch `3 → 5/6/7`: prefer two graphs sharing Compound `3`. Its local roles
  are terminal then root; add a hub highlight only with source support. If the
  authors prioritize `6`, give `6` a separate `paper_selected` highlight.
- `10 → 11/12` explores a side chain and `10 → 21/22` explores an independent
  ring series: two theme-based graphs can share `10`. Its two branches alone
  do not establish a hub highlight.
- `30 → 31 → 32`, a short progression: usually one graph; `31` is not
  automatically a hub merely because it is intermediate.
- `40 → 41/42`, plus independently supported comparisons `41 → 43` and
  `42 → 43`: keep the convergence when it clarifies SAR. Two incoming SAR
  edges do not assert a joint synthesis from two reactants.

### Separate graph position from scientific role

| Context | Meaning and current representation |
|---|---|
| Synthesis `root` | No incoming edge and at least one outgoing edge in this group; may be a co-reactant rather than the originating lead. |
| Synthesis `intermediate` | Both incoming and outgoing edges in this group. |
| Synthesis `terminal` | At least one incoming edge and no outgoing edge in this group; not proof of an absolute route endpoint or selected lead. |
| Isolated member | No incident edges: do not call it root or terminal. Use `unspecified` with an explanation if retained pending review, or remove only the unjustified membership while preserving the Compound and other memberships. |
| SAR baseline / comparison entry | A documented baseline may be `root`; a graph entry inferred only from direction must be described as such. Other members may remain `unspecified` with their comparison role explained. Do not impose synthesis roles on a parallel comparison. |

Roles are scoped to a particular Lineage. The same Compound can be a synthesis
intermediate and a SAR baseline, or terminal in one SAR graph and root in the
next. SAR intermediate means an intermediate design/comparison position, not
necessarily a synthetic intermediate. A local SAR root can be an initial study
starting point or a later hub used as that graph's baseline. Check roles again after adding/deleting/moving
edges. Surface conflicts with existing human annotations for reconciliation;
do not silently overwrite them using degree counts.

### Article-level starting points, hub compounds and prioritized compounds

Use optional payload compound_highlights for source-backed `study_start`,
`optimization_start` (枢纽分子 / Hub compound), and `paper_selected` assertions.
These are orthogonal to Lineage roles, not a fourth
member role and not the biological target. A study starting point is the hit/lead
from which the authors pursue this work, not every synthetic reagent. A
paper-prioritized compound is explicitly selected or advanced by the authors on
combined evidence, not every terminal or the best number in one assay.

A hub compound is used by the authors as a design baseline or transition into
further optimization. Record the named batch/series and the source-supported
transition in scope and rationale. It need not have multiple outgoing branches,
be the most potent compound, or be paper-prioritized. Graph degree, position,
splitting, and synthetic-intermediate status alone never establish this role.
Keep the storage key `optimization_start`; do not invent a `hub` role or replace
the local `root/intermediate/terminal/unspecified` member roles. A hub highlight
does not automatically split or otherwise change a graph.

Each annotation requires a unique ref, compound_ref, evidence_ref, role, nonblank
scope (whole paper or named study/series), and rationale. Optional review_hint
records ambiguity. The Compound and Evidence must be present in the same payload.
Evidence must locate the author statement using actual PDF page and quotation or
region; rationale explains the role and retains its limits. Multiple starts,
multiple hubs, multiple prioritized compounds, and multiple roles on one Compound are allowed;
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

Treat the three roles independently. `study_start` may contain both a literature
hit and the paper's internal lead when the article uses both scopes; state the
scope in `scope` and do not collapse them into one label. `paper_selected` may
contain several compounds when the authors name a set of leads, candidates, or
parallel endpoints. Add one highlight per compound/role/scope, or leave the
role unresolved when the source does not justify a single choice. Never replace
a multi-compound conclusion with the strongest-looking member. `optimization_start`
records supported design transitions in the relevant series. The same Compound
may also be `study_start` or `paper_selected` when each assertion has its own
supported scope and rationale. Article information and graph badges refer to
these same highlights; do not create a separate graph-only prioritized label.

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

### 文章元数据：每篇主动检查 Abstract 与研究主题

每篇任务都必须主动检查文章元数据，不再以“可选字段”为理由略过摘要。优先在授权来源中检查原文 Abstract；将原文保存到 `bibliography.abstract`，位置写入 `abstract_source`，状态设为 `abstract_status: extracted`。保持原文含义和段落，不把模型总结、翻译或 Introduction 当原文摘要。

没有交付摘要时必须写 `abstract_status` 和 `abstract_note`，并在 omissions 加 `payload.bibliography.abstract`：已检查授权来源但未找到为 `not_found`；无法提取、来源冲突或范围未完成为 `needs_review`；确未检查为 `not_checked`，明确列为未完成。`not_found` 只表示已检查范围内未找到，不能推断所有来源都没有。已有摘要的局部修补不得清空或改写人工文本。

`pmid` 与 `pmcid` 分别保存 PubMed 数字 ID 和 PMC accession，身份核验依据写 `identifiers_source`。只使用授权来源或冻结的已核验书目记录；DOI 精确匹配并核对题名/年份后才配对。不凭 DOI 格式或标题猜 PMID，也不为补字段扩大工具/网络权限。

`research_profile` 为文章研究主题对象：`modalities`（分子类型，兼容存储键）、`mechanisms`（作用方式/机制）、`diseases`（疾病/应用）、`optimization_goals`（优化目标）各为多项数组，每项 `{label, source, review_hint?}`。每项必须有具体来源位置；未知不猜测，空数组不是“原文未报告”的证明。优化目标与实际达到的结果不同，不能把目标写成成功结论。

`modalities[].label` 用于“分子类型”同一模块内两组可交叉、多选的固定标签，保留历史存储键，不新增独立“分子形式”模块：

- 主要类型：`小分子抑制剂`、`小分子激动剂`、`小分子拮抗剂`、`小分子反向激动剂`、`小分子激活剂`、`小分子调节剂（作用待细分）`、`PROTAC`、`分子胶`、`其他`、`待明确`。
- 补充特征：`变构调节`、`共价作用`、`大环类`、`肽／肽模拟物`、`前药`。

每篇至少选择一种有据的主要类型；主要类型不足以确定时选择待明确并解释，不靠补充特征替代主要类型。不要重复同一标签。`其他`、`待明确` 必须有简短 `review_hint`；小分子调节剂（作用待细分）也应说明具体已知作用与未决范围。常规受体 agonist 与 enzyme activator 分别对应激动剂、激活剂，inverse agonist 不混作 antagonist。抑制剂、变构与大环可以同时成立；不可逆不自动证明共价。分子胶不自动等同降解剂；具体诱导的相互作用/降解留在 mechanisms。

仅按本文实际优化的分子系列分类，不因背景介绍、对照药、起始工具分子或安全性脱靶检测给整篇文章加类型。若多个优化系列不同，每个标签的 source 说明适用系列，不能暗示所有分子都有所有特征。大环肽不得自动标成常规小分子抑制剂：可用其他（说明肽类抑制剂）＋肽／肽模拟物＋有据的大环类。仅有表型活性或观察到通路蛋白下调不证明直接抑制；依据不足时如实解释。机制详情仍放 mechanisms，类型标签用于摘要浏览/筛选。

每个标签独立提供原文依据与 evidence，科学运行核对原文后才转换旧的“直接靶点调节”等宽泛标签；不得机械替换为小分子抑制剂。新提取使用新词表，未授权修订的历史数据不自动改写。明确授权的分类修订只替换 modalities，其他 profile 组、摘要、靶点、PDB、人工笔记保持原样；旧证据可在实际支持新标签且经复核时复用，旧提交始终保留。

`molecular_forms` 已退出新提取和普通文章界面。新候选不要生成该组；有依据的大环/肽等特征使用上述分子类型的补充特征标签，其他相关骨架信息可在机制/优化条目的说明中表达。历史 schema 仍读取该键以保持冻结快照和人工内容兼容；局部修补不批量删除历史值，也不能为了规范词条改写范围外内容。旧模态若无法无歧义归类，保留原词/来源并报告待核对，不能强制映射。

文章阅读区只展示 Abstract 正文；`abstract_source` 和 `identifiers_source` 是内部追溯字段，仍应准确记录。正常 `extracted` 情况下不新增“按 DOI 核对”“管理员补充”“摘要来自某数据库”等过程说明到 `abstract_note`。该说明仅用于实际缺失、冲突或未决问题；不要清除已有人工问题。

`research_profile.targets` 每项为 `{name, role, organism?, gene_symbol?, uniprot_id?, ncbi_gene_id?, source, review_hint?}`。role 为 primary/co_primary/selectivity/off_target/mechanistic/biomarker/unknown，区分主要靶点、共同靶点、选择性对照、脱靶、机制相关和标志物。保留物种，不默认人类；未能确定标准基因或 accession 时只保留来源名称，复合物或表型研究不强配一个基因。不得从靶点常识推断疾病。具体 Compound 属性、活性数值和 Lineage 仍在其原记录中维护。

`bibliography.pdb_references` 是提及记录数组，每项包含 `pdb_id`、`usage`（`this_work` / `cited_structure` / `unknown`），以及可选的 `source_page`、`source_context`、`compound_label`、`review_hint`。PDF 页码从 1 开始，不能超过原文件页数。保留用途和来源上下文；只有来源明确配对时才填写 compound_label，不凭 docking 常识猜配体对应。无法确定用途用 unknown 并简要写核对提示。

PDB ID 接受传统四字符（例如 1ABC）和扩展格式（例如 pdb_00001abc）；三字符配体代码（ATP 等）、DOI、UniProt ID 不属于此字段。同一个 PDB ID 在不同上下文中可多次出现，不能据此把引用结构认作本文新解析结构。不要查询外部结构反推论文未报告的编号。旧候选可不含这些字段；对既有文章补录仍遵守版本化修改及人工编辑保护。

### 文章条目的原文证据

SourceBackedLabel、ResearchTarget 和 PdbReference 可有 `evidence` 数组。新提取应为每个可支持的条目提供直接原文短摘录，不把 `source` 的解释或译文冒充引文。证据格式：`{source_kind: main_pdf|supplement|external, quoted_text, page_number?, locator?, source_url?, source_sha256?, bbox?}`。`quoted_text` 是保持原语言的精确原句/短段（最多 6000 字符）；PDF 两类都必须使用从 1 开始的 PDF 物理页码，补充材料另需 locator 标识材料名称；external 必须给无凭据的 http(s) 来源 URL。基因数据库补充须标外部来源，不能暗示文章报告了 accession。

准确且确有需要时可附主文 `bbox:{x,y,width,height}`（全页归一化坐标，矩形不得越界）；必须同时附主 PDF SHA-256。未确定坐标就省略 bbox，不猜测截图。未能找到直接支持的摘录时省略 evidence，保留原 source/review_hint 并在未决中列出；缺失不是“论文未报告”的证明。历史 candidate 可缺少 evidence。修补仅追加获核对的证据，保留所有人工字段、条目顺序和既有引文。


### 批量补齐已有文章信息

批量任务先逐篇冻结 submission hash、workspace version、来源身份及现有文章字段，并记录本次待审清单；已完成条目只核对覆盖情况，不重复追加同一引文。对缺失的研究主题与摘要、标识符逐项检查；字段有值不等于科学正确，但本次追加任务不得替换人工值，发现冲突应记录待核对。空研究主题可以补齐完整的受支持主题；已有主题/条目保持顺序和字段，只追加已核对且不重复的证据。未知、未检查、来源不可得、检查后未找到必须分别报告，不能以空数组表示已完成核验。

原文证据通常每项提供 1–2 段紧贴论断的短摘录；复杂项可拆分多段。只允许空白及换行规范化，不得拼接不相邻段落冒充连续原文。分别核对 PDF 物理页、栏位、边界和对应条目；跨栏抽取混乱时检查原图。主文证据与外部基因 accession 核验分开标明，保存准确 URL；外部标识符不等于论文自己报告该 ID。只在实际取得的来源中取证，缺 SI 时明确列出受影响项，不生成虚构补充材料证据。既有摘要原文保持不变，补齐缺失状态/来源也必须与所核对的内容相符。

本类文章信息补填不构成全篇 Compound/Activity/Lineage 复核；完整化合物清点覆盖与缺口应标记 not_reaudited/unknown。每篇都要保存实际已查字段、未决项及真实生产者自检/新会话复核身份；复核会话内修改后的自检不能称为第二次独立复核。

## Original-paper Activity tables and Other

Preserve the source table organization as optional `payload.activity_tables`,
without duplicating Activity values. Every Activity used by a table must have a
unique stable `ref`. A table has `ref`, editable `name`, `kind: "source"`, exact
`source_label` (for example `Table 2` or `Table S1`), `source_title`, and PDF
`page_number`. Its ordered `columns` have stable `id`, display `label`, exact
Activity `assay`/`metric`/`unit`, and explicit `activity_refs`. Keep flattened
multi-level headings legible (for example `Human · IC50`); preserve species,
concentration and time distinctions in the heading and each Activity context.
Never assign records merely because two measurements have similar names or
Compound coverage. Distinct source tables remain distinct even with identical
column headings. A column contains only observations with its exact measurement
identity. Repeated observations remain separate Activity refs; do not average,
round, convert values or invent missing cells to make a rectangular table.

The application derives **Other** from Activities not referenced by any saved
table. Do not emit a synthetic source table named Other or duplicate records to
populate it. Text/figure-only observations belong there. Unknown table assignment
also remains there with an explicit Activity `review_hint` explaining the
uncertainty; do not assert that an unlocated observation is absent from all source
tables. Source Table grouping never limits the full Compound/Activity inventory.
If a source table contains unsupported non-Activity content, retain the supported
Activity columns and explain the unrepresented material in omissions/context.

For scoped table revision, preserve existing Activity refs, all scientific values,
Compound structures, human notes and unrelated fields. Return the complete
candidate, changing only authorized table definitions and necessary dependencies.
Existing custom/reviewer tables and labels are protected unless explicitly in
scope. New records require new stable refs; never recycle a removed record's ref.
Use `activity_refs` to bind each cell explicitly, not a label-matching heuristic.
Do not claim reviewer confirmation: imported or changed tables are draft and
changed claims/dependents require Reviewer reconfirmation. AI provenance remains
in audit history and is excluded from Reviewer-only approval differences; later
human corrections remain reviewable. Submitted snapshots are never rewritten.
