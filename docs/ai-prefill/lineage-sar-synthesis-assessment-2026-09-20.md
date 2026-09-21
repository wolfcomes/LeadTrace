# SAR versus synthesis Lineage: assessment and proposed model

Status: assessment only, based on the current seven-workspace scientific snapshots
and the existing Lineage schema. No scientific categories have been assigned by
this UI revision, and no schema migration has been applied.

## Why distinguish them

| Semantic category | Meaning of A → B | Typical support | What it does not establish |
| --- | --- | --- | --- |
| SAR / design comparison | A is a reference structure or design starting point for comparison with B | SAR tables, design narrative, structure comparison and assay records | Actual synthesis from A; chronological discovery order; improved potency |
| Synthesis / chemical transformation | The paper reports or AI infers a chemical route from precursor A to product B | Scheme arrows, experimental procedures, transformation descriptions | Better activity; use of A as the medicinal-chemistry design baseline |

Scientific relation category, evidence availability, extraction/inference basis,
and review status are separate dimensions. A SAR comparison can be explicitly
reported; a synthesis relation can still be an AI inference. Missing text Evidence
must not prevent either category from being recorded. Unsupported endpoints or
intermediates should not be invented to make a graph connected.

## Evidence in the current dataset

Paper 004 (PfPKG):

- R1–R5 contain 38 `sar_baseline_comparison` Edges from compound 1.
- “合成转化补充 · Scheme 3–5” contains nine explicit synthesis-type Edges, including
  `1 → 21` bromination, `21 → 23` cyanation and `23 → 26` nitrile hydrolysis.
- The original six-Edge Lineage uses transformation names such as `cross_coupling`
  and `formylation`. These are synthesis candidates but historical provenance and
  existing source conflicts must be reviewed before formal migration.
- `1 → 21` exists in both a SAR Lineage and a synthesis Lineage. This is meaningful:
  two semantic relations can share endpoints and should not be deduplicated merely
  by compound pair.

Paper 009 contains mixed Lineages today. The first JUG series combines
`mono-substitution SAR analog` with `synthetic deprotection`; the second combines
`disubstitution SAR analog` with `synthetic hydrolysis`. A Lineage label or reference
to “Scheme” is therefore insufficient for automatic classification.

Paper 005 also combines analog-change vocabulary across several Lineages with a
separate series of `ester_hydrolysis` and `Boc_deprotection` relationships. Other
records use free-form `substituent_replacement`, `SAR exploration`, `potency
optimization`, and similar strings. Those names alone are not proof of provenance.

## Existing schema

`Lineage` has a label and description, but no dedicated semantic category.
`LineageEdge.relation_type` is a free-form string used for both chemical changes
and conceptual relations. It cannot reliably serve as the sole category field.
Current SAR/synthesis naming is descriptive, not a stable filtering contract.

## Revised recommendation after checking Materials and Methods

The user's follow-up focuses on separate scientific narratives, rather than only
filtering a mixed graph. Recommend **separate SAR and synthesis Lineage records**,
sharing existing Compound identities where the chemical form is genuinely the
same. Use explicit Lineage type (`sar`, `synthesis`, `unspecified`) for grouping and
keep Edge-level relation semantics for validation. Mixed historical Lineages should
be flagged during migration and reviewed/split; “mixed” is a transition state, not
the preferred organization for new extraction. This supersedes the earlier
recommendation to rely chiefly on an aggregated Lineage category.

Source-section provenance is a separate field/annotation: section, subsection,
page and exact text/image region. Do not make “Materials and Methods” itself a
semantic type: it also contains assay methods, while Results can include synthesis.
One synthesis Edge may have both Scheme and experimental-procedure Evidence.

Concrete checks in this PfPKG article (PDF pages, not journal pagination):

- Page 3: Results → Synthesis and Scheme 2 already summarize chemistry.
- Page 8: “R1 − In Vitro SAR Trend” compares 12a/b, 18a/b, 19a/b and others with
  parent 1 and discusses potency; these are SAR comparisons.
- Page 16: Materials and Methods begins.
- Pages 17–18: “Synthesis of Final Compound 1 Following Route Outlined in Scheme
  2” specifies 9g preparation, 9g plus iv leading to 10g, cyclization to 11g,
  conversion to free base 1-fb, then preparation of the salt labelled 1.
- Page 23: the 19a procedure explicitly uses 18a-fb to produce 19a-fb, followed by
  conversion to the salt 19a. This experimental-form distinction is absent from a
  coarse `18a → 19a` compound-family arrow and must be documented before claiming
  a complete experimental route.
- Page 23 also prepares 19b through intermediate 60 from 67. Therefore summarized
  Scheme-family connections should not automatically be labelled as the exact
  experimental precursor sequence without checking the detailed procedures.

Current 004 snapshot contains 10g and 11g but not 9g or a separate 1-fb record.
The existing 44-compound review set therefore must not be described as covering
all Materials and Methods intermediates or all chemical forms. This follow-up
identified coverage limits; it did not add records or revise existing Edges.

Suggested separate records:

- SAR: R1 pyridine substitutions; R2 pyrrole-carbon substitutions; R3 ring changes,
  etc. Focus on design comparison, comparable Activity endpoints, interpretation
  and source Evidence. Display these first for lead-optimization review.
- Synthesis: route to compound 1 (Scheme 2 + experimental procedures), routes to
  R1 analogs, routes to R2 analogs, etc. Include validated precursors/intermediates,
  reaction types, conditions/yields when reported, and exact experimental evidence.
  Group connected/shared-intermediate routes as appropriate rather than creating
  one enormous synthesis graph or one Lineage for every isolated step.

An assayed compound can be a SAR reference/member and a synthesis product/member.
Its Compound identity and Activity records are shared, while membership roles and
Edges are specific to each Lineage. A protected precursor, a free base and a salt
must not be blindly merged because their numeric labels are related. Non-assayed
intermediates should show “no Activity record,” and should not be inserted into SAR
Lineages solely to make compound membership coverage look complete.

UI: separate SAR / Synthesis sections or tabs within Lineage; retain independent
point/structure display switching. Compound details can link to the relevant SAR
and synthesis Lineages. Use Edge semantics to catch accidental cross-category
entries. A combined overview, if later useful, is secondary to these separate
records.

AI prefill: first inventory article sections; separately extract SAR comparisons
from the narrative/tables and synthesis routes from Schemes, experimental methods
and Supporting Information. Reconcile shared compounds and chemical forms after
both passes. Audit SAR-analog coverage and synthesis-intermediate/step coverage
separately. A missing text quotation must not reject an AI-inferred relationship;
record inference versus source extraction and unresolved chemistry explicitly.

Migration: propose reviewable assignments/splits for existing Lineages, preserving
Compound identity, Evidence, review state and known conflicts. Update Lineage type
in create/edit APIs, snapshots/exports and AI-prefill contracts together. Do not
classify by heading or relation-name regex alone, duplicate shared compounds, or
silently replace a summarized route with claimed experimental steps.

## Alternative and limits

Only adding color/category badges to a single mixed graph does not address the
user's need for separate SAR and synthesis narratives. Conversely, splitting by
article section alone can misclassify chemistry in Results or assays in Methods.
Explicit separate Lineages plus Edge semantics and source provenance address both.

The current graph has binary parent/child Edges. “Synthesis Lineage” should initially
mean recorded compound transformations, not a complete executable reaction route.
Multi-reactant steps, conditions, reagents and omitted intermediates need a separate
reaction/step model if full route reconstruction is later required. A multi-step
reported connection should be labelled accordingly, not presented as a single
reaction by default.
