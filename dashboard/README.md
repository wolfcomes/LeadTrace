# Lead Optimization Control Room

This is a local dashboard for the 2024 JMC lead-optimization pipeline. It
reads the current CSV/JSON snapshots under
`source_pdfs/分子修改提取_2024_JMC`, presents one row per Paper, and serves
reviewed evidence PNGs without copying or modifying the source data.

## Start

From the workspace root:

```bash
python dashboard/server.py --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/> in a browser. The port can be changed if another
local service is already using it.

## Views

- Project overview is the first top-level view. It separates corpus, evidence,
  candidate, structure, and final-path counts and does not collapse them into
  one completion percentage. Overview metrics and pipeline rows link into the
  Paper library with a relevant filter.
- Paper library is the second and only other top-level view. All 672 Papers
  appear as individual records in stable manifest order, with 20 records per
  page (34 pages; 12 records on the last page), search, pipeline-stage
  filtering, and human review-status filtering.
- Clicking a Paper opens its full Paper workspace. The workspace shows source
  metadata, text extraction, and a single unified review list. Each entry keeps
  its evidence statement, activity, candidate modification, explicit path,
  SMILES/RDKit result, attached OCSR result, and entry-level review controls in
  one review box. Candidate records are the primary entries; evidence without
  a candidate remains as an evidence-only entry. Missing values display as
  `--`. The old global structure, OCSR, and evidence navigation entries are
  intentionally removed. In 修改模式, the same box exposes typed controls for
  page numbers, statuses, compounds, evidence/activity text, and SI/canonical
  SMILES. It also supports saving a draft, adding a manual entry, deleting an
	 unconfirmed entry, and confirming one entry for synchronization.
- Paper details include a compound optimization lineage section before the
  Objects and unified-review sections. Each lane distinguishes the root
  template from the immediate parent and derived compound, supports branches
  and multiple independent roots, and keeps relation status separate from
  structure status. Unresolved direct parents stay visible as unresolved edges.
- Only lineage edges backed by an explicit relation and two complete,
  parseable compound SMILES become `molecule_pair` review items. Both sides are
  redrawn uniformly with RDKit. The review item retains its lineage, root,
  parent, derived, relation, evidence, and activity metadata through draft and
  confirmation persistence.
- `parent_object_id` and `derived_object_id` describe image containment or
  scaffold/fragment association only. They never generate medicinal-chemistry
  pairs. Filtered Objects remain available as source evidence, while R groups,
  sites, linkers, and shared scaffolds cannot become either side of a complete
  pair.

- The project overview also contains a chemistry-first first-page review for
  the first 20 manifest Papers. It shows the 31 PDF image candidates in crop,
  fragment/series/whole-molecule scope, attachment-point reasoning, and
  proposal-only SMILES/RDKit states. A syntactically valid SMILES from a
  non-structure or mixed crop is not counted as chemically accurate.
- The same first-page review now has an object-level layer. It expands each
  candidate into numbered molecule members, shared scaffolds, replacement
  fragments, variable sites, linker fragments, and explicit non-structure
  regions. Each object keeps a local crop and normalized bounding box. Only
  objects marked as locally isolated are eligible for the next OCSR batch;
  R/Site/linker endpoints remain notation-only until connectivity is reviewed.

## Read and edit modes

The header switch changes between 阅读模式 and 修改模式. Reading is always
available. In 修改模式, Papers whose review status is not `reviewed` can
receive a revised title, correction text, status, and note. Saving sends the
review to the server-side Paper review file described below. A reviewed Paper
is locked against later ordinary overwrite requests.

## Review boundary

DECIMER results are proposals only. OCSR crops are shown as model input and
never automatically become final structures. Paper review edits are separate
from the pipeline and never write to
`06_text_confirmed_paths/explicit_text_confirmed_paths.csv`.

## Paper review persistence

The dashboard stores human Paper edits in:

```text
source_pdfs/分子修改提取_2024_JMC/09_paper_review/paper_review_overrides.json
```

The file contains only known manifest Paper IDs. It stores Paper-level fields
(`review_status`, `title_override`, `correction_note`, `review_note`) and
Paper-entry draft operations (`review_items`, `added_items`, and
`deleted_items`). Writes use a temporary file and atomic replacement.

After an entry is explicitly confirmed, its flattened, reviewable values are
written to:

```text
source_pdfs/分子修改提取_2024_JMC/09_paper_review/reviewed_entries.csv
```

Confirmed entries are locked against later edits and deletion. Adding an item
with `review_status=reviewed` is rejected; the confirm endpoint is the only
route that writes the curated row. Original manifests, PDFs, extracted CSVs,
structure confirmation CSVs, and generated images remain read-only.

Confirmed lineage-pair rows additionally retain `lineage_id`,
`lineage_edge_id`, `root_template_entity_id`, `root_template`,
`parent_entity_id`, `derived_entity_id`, `relation_status`,
`relation_confidence`, `pair_kind`, and both complete SMILES. Confirming a
saved draft merges the final status into the existing content rather than
replacing those reviewed values.

The server only exposes PNGs by basename from the approved
`05_visual_review/explicit_path_pages`, `08_ocsr_benchmark/crops`,
`09_structure_confirmation/generated_structures`, and generated
`09_paper_review/auto_fill/molecule_pair_structures` directories. Article page
images remain evidence assets; they are not used as final molecule renders.
It rejects path traversal and does not expose arbitrary files.

## Structure confirmation pilot

The 16 explicit paths are joined to SI-sourced SMILES in
`09_structure_confirmation/compound_smiles_reference.csv`. Rebuild the
read-only structure dataset and RDKit PNGs with:

```bash
python source_pdfs/分子修改提取_2024_JMC/scripts/structure_confirmation.py
```

This writes `confirmed_path_structures.csv` and one parent image, derived
image, and side-by-side path panel per explicit path. The output status remains
`structure_confirmed_pending_human_review`; sourced SMILES do not by themselves
promote a path to the final confirmed dataset.

## Compound optimization lineages

The current lineage snapshot is generated from reviewed direct-relation
annotations, complete structure references, and compound activity records:

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  python source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py
```

It writes `compound_entities.csv`, `compound_lineage_edges.csv`,
`compound_lineage_evidence.csv`, `compound_activities.csv`, and
`compound_lineage_summary.json` under `09_paper_review/auto_fill/`. The first
validated Paper has two independent roots, 25 recorded edges, 22 complete-pair
eligible edges, and three edges whose direct parent remains unresolved.

## API

- `GET /api/overview`
- `GET /api/first-page-structure` for the first 20 Paper fragment-aware image
  review snapshot
- `GET /api/first-page-molecule-objects` for the object-level first-page
  localization snapshot and local molecule/fragment crops
- `GET /api/papers?q=&status=&review_status=&page=&page_size=20`
- `GET /api/papers/<paper_id>` for the complete Paper workspace payload
- `POST /api/papers/<paper_id>/review` for a validated Paper review override
- `POST /api/papers/<paper_id>/review-items` to add a manual review entry
- `POST /api/papers/<paper_id>/review-items/<review_item_id>` to save one entry's
  typed content, review status, and notes as a draft
- `POST /api/papers/<paper_id>/review-items/<review_item_id>/confirm` to lock
  one entry and synchronize it to `reviewed_entries.csv`
- `DELETE /api/papers/<paper_id>/review-items/<review_item_id>` to hide an
  unconfirmed entry from the Paper workspace
- `GET /api/paths?scope=explicit|unresolved|all&q=&priority=&status=&page=&page_size=`
- `GET /api/paths/<visual_review_id>` for an explicit path detail
- `GET /api/proposals?visual_review_id=`
- `GET /assets/pages/<basename>.png`
- `GET /assets/crops/<basename>.png`
- `GET /assets/structures/<basename>.png`
- `GET /assets/molecule-review-crops/<basename>.png`

The isolated-object OCSR batch is separate from page-crop OCSR:

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  .venv-jmc-ocr/bin/python source_pdfs/分子修改提取_2024_JMC/scripts/run_first_page_molecule_ocr.py
```

It currently runs only objects whose local crop is ready. The output in
`09_paper_review/auto_fill/first_page_molecule_proposals.csv` is proposal-only;
`rdkit_status=valid` means the string parses, while
`valid_but_suspicious_needs_review` means the result still contains one or
more signs of a wrong image interpretation such as extra components or
unusual atoms. The heuristic primary component is displayed as a review aid,
not as a confirmed SMILES.
