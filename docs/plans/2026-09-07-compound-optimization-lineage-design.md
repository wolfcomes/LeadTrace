# Compound Optimization Lineage Design

## Goal

Record the medicinal-chemistry optimization history in each Paper as a directed lineage graph. A lineage must distinguish the original template, the direct parent used in each iteration, and the derived compound. Image objects remain source evidence and must never be interpreted as compound lineage solely because one crop contains another scaffold or fragment.

## Core Model

Each Paper can contain multiple independent lineages. A lineage is represented by reusable compound entities connected by directed modification edges:

```text
root template -> direct parent -> derived compound
                           \-> alternative derived compound
```

The same compound entity is stored once and can participate in several edges. `root_template_entity_id` is materialized on each edge for review and filtering, while `parent_entity_id` always means the immediate medicinal-chemistry parent. A root may be an external named drug, a known inhibitor, a prior-art compound, or an in-Paper lead.

For example, the current GLP-1R Paper contains at least two lineages supported by explicit text:

```text
danuglipron -> compound 3 -> compounds 8/9/10
prior-art compound 2n -> compound 23 -> compound 24
```

Number adjacency, location in the same figure, structural similarity, and `parent_object_id` are not sufficient to confirm an edge.

## Data Files

### `compound_entities.csv`

One row represents one chemically meaningful compound within a Paper-specific namespace.

Required fields:

- `compound_entity_id`: stable ID such as `CMP-<paper_id>-<normalized-label>`;
- `paper_id`, `display_label`, `normalized_label`, and optional `preferred_name`;
- `entity_origin`: `external_reference`, `prior_art`, or `in_paper`;
- `entity_role`: `root_template`, `lead`, `iteration_intermediate`, `derived_compound`, or `unresolved`;
- `compound_object_ids`: matching complete-molecule image objects only;
- `canonical_smiles` and `structure_status`;
- `structure_source_type`, `structure_source_locator`, and `structure_review_status`.

Fragments, R groups, variable-site markers, and shared scaffolds are not compound entities unless a complete molecular graph has been reconstructed and reviewed.

### `compound_lineage_edges.csv`

One row represents one direct optimization step. Branches are represented as several rows sharing the same parent.

Required fields:

- `lineage_edge_id`, `lineage_id`, and `paper_id`;
- `root_template_entity_id`, `parent_entity_id`, and `derived_entity_id`;
- `parent_role` and `iteration_depth`;
- `modification_site`, `from_group`, `to_group`, and `relation_type`;
- `relation_status`: `text_explicit`, `figure_explicit`, `context_inferred`, `structure_suggested`, `unresolved`, or `rejected`;
- `relation_confidence`, `review_status`, and `review_note`.

`context_inferred` and `structure_suggested` edges remain candidates until reviewed. Only explicit or human-confirmed edges are treated as established modification paths.

### `compound_lineage_evidence.csv`

One edge can have multiple evidence records. Text, figure, table, and image evidence are kept separate so reviewers can inspect the exact basis of the relationship.

Required fields:

- `lineage_evidence_id` and `lineage_edge_id`;
- `evidence_type`: `text`, `figure`, `table`, `scheme`, `structure_similarity`, or `manual`;
- `page`, `source_locator`, and `evidence_text`;
- `source_object_ids` for relevant structure crops;
- `evidence_strength` and `review_status`.

### `compound_activities.csv`

Activity is compound-level assay data, not part of the identity of a lineage edge. Each measurement records `compound_entity_id`, assay/target, metric, comparator, value, unit, qualifier, page, and source text. The UI can calculate or display the parent-to-child activity change without flattening multiple assays into one ambiguous string.

## Object And Structure Boundaries

`first_page_molecule_objects.csv` continues to describe image-localized objects. Its `parent_object_id` is renamed conceptually to an image-containment or scaffold-association link and is never consumed by the lineage builder.

Complete structures are resolved in this order:

1. Paper/SI structure table with an exact compound-label match;
2. reviewed external source for a named drug or prior-art compound;
3. visually verified OCSR/reconstruction of a complete molecule;
4. scaffold plus R-group assembly with all attachment points resolved;
5. otherwise `canonical_smiles=--` and `structure_status=missing_or_fragment_only`.

RDKit parsing validates syntax and supports canonicalization/rendering. It does not confirm that the structure matches the Paper.

## Edge Construction Rules

The builder processes evidence in this order:

1. Detect root-template language such as `based on X`, `derived from X`, and `using X as a lead`.
2. Detect direct transformations such as `optimization of X yielded Y`, `applied to X leading to Y`, and `based on X ... compound Y`.
3. Expand one-to-many series only when the parent and every child are bound by the same explicit statement or table context.
4. Resolve each compound mention to a Paper-local entity and then attach complete structure sources.
5. Use maximum-common-substructure or similarity only to rank unresolved parent candidates; never auto-confirm an edge from similarity.
6. Reject synthesis-only precursor/product reactions from the medicinal-chemistry lineage unless the text identifies them as an optimization relationship.

Comparison language alone, such as `more potent than compound X`, does not prove that X is the parent. Number adjacency never proves a lineage.

## Review And UI

The Paper detail page presents a lineage before the flat review list:

- one lane per independent `lineage_id`;
- root template shown once at the start of the lane;
- each direct edge shown as a complete parent/derived molecular pair;
- branches grouped under their direct parent;
- evidence and relation status shown independently from structure status;
- unresolved edges retained with `--` structures instead of fabricated pairs;
- edit mode allows changing the root, direct parent, child, relation, evidence, and review state.

The existing Objects section remains an evidence browser. Fragment/scaffold objects can be linked from an edge's evidence but do not appear as either molecule in the pair.

## Acceptance Criteria

- No molecule pair is generated solely from `parent_object_id` or `derived_object_id` in the object table.
- Every displayed pair references a lineage edge with distinct parent and derived compound entities.
- The root template and immediate parent are both visible and queryable.
- A Paper can contain multiple roots, branches, and multi-step chains.
- Relation confidence and structure confidence remain separate.
- Both pair images are regenerated from complete, RDKit-valid SMILES; otherwise the missing side displays `--`.
- Source PDFs, source CSVs, and previously confirmed structures remain unchanged.
