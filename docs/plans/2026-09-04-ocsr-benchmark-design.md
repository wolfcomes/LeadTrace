# OCSR Benchmark Design

## Purpose

Build a reproducible, auditable OCSR benchmark for the 16 unique
text-directed molecular-modification paths in the 2024 JMC corpus. The
benchmark produces structure proposals only. It must not promote a proposed
SMILES string to a confirmed compound structure or modify an existing path
status.

## Scope And Boundary

Each path has a parent compound and a derived compound. The benchmark will
therefore process up to 32 explicitly curated structure crops. Each crop must
record its source PDF, source page, rectangle in PDF points, compound label,
and rendering settings. The crop manifest is the authoritative link between a
model result and its visual evidence.

DECIMER receives only cropped single-structure regions. It must not receive a
full evidence page, a whole manuscript page, a compound-activity table, or a
general synthetic Scheme without a resolved target structure. Those inputs
would make an OCSR result ambiguous and unsuitable for review.

## Selected Approach

The selected approach is human-guided localization followed by automated,
reproducible extraction and validation:

1. A reviewer identifies the exact PDF page and rectangle containing each
   target compound structure, then enters the location in a CSV manifest.
2. A script re-renders every rectangle from the original PDF at a fixed 300
   DPI, saves the crop, and checks that its label and source evidence are
   complete.
3. DECIMER runs against those immutable crop images and records its raw SMILES
   proposal and token-confidence summary.
4. RDKit parses and canonicalizes every proposed SMILES. Invalid or empty
   proposals remain in the results table with an explicit failure status.
5. A reviewer compares the crop, the proposed structure, the named compound,
   and the text evidence before manually promoting any result to a later,
   separately governed confirmed-structure dataset.

## Rejected Alternatives

- Full-page DECIMER inference: Evidence-page inspection shows that the pages
  combine prose, tables, protein images, reaction arrows, and multiple
  structures. It cannot reliably identify the intended compound.
- Automatic page segmentation first: This is useful only after a manually
  assessed pilot establishes a sufficiently accurate detection method. It
  would introduce another unvalidated model stage into the first benchmark.
- Writing model output directly into `06_text_confirmed_paths`: DECIMER is an
  OCSR proposal generator, not a confirmation source. Direct writes would
  weaken the evidence trail.

## Runtime And Model Assets

The project virtual environment is
`/data/home/zhangzhiyong/lead_optimization_collection/.venv-jmc-ocr`.
TensorFlow 2.16.1 requires the nested NVIDIA package library directories in
`LD_LIBRARY_PATH` before import. A wrapper will build that value dynamically
from the active Python environment and verify a real GPU operation before
DECIMER inference.

DECIMER model files must be cached under the project-owned benchmark directory,
not an untracked home-directory cache. The model archive is fetched from Zenodo
with `curl --continue-at -`, validated as a ZIP archive before extraction, and
retained only after the expected SavedModel artifacts exist. This makes
interrupted downloads restartable without accepting an incomplete archive.

## Outputs

All new benchmark artifacts live under `08_ocsr_benchmark`:

- `structure_crop_manifest.csv`: reviewed source rectangles and compound
  labels.
- `crops/`: deterministic PNG renderings of each declared rectangle.
- `decimer_model/`: local DECIMER model cache, excluded from review data.
- `ocsr_proposals.csv`: raw and canonicalized model proposals, RDKit status,
  confidence summary, provenance, and review state.
- `benchmark_summary.json`: counts, versions, GPU execution evidence, and
  unresolved items.

## Quality Gates

- A crop manifest row must point to an existing PDF, a valid positive page, a
  non-empty compound identifier, and a positive-area rectangle.
- Generated crops must be non-empty PNGs and remain traceable to the manifest.
- DECIMER inference must first prove that TensorFlow can execute a GPU matrix
  operation. CPU fallback is reported explicitly and is not silently accepted
  for the planned benchmark.
- RDKit validation and canonicalization must preserve the original model
  proposal alongside the result.
- Every result remains `proposal_requires_human_review` until a person reviews
  it.

## Success Criteria

The pilot is complete when the project contains an auditable crop manifest and
generated crops for the chosen compound structures, DECIMER has produced a
record for every eligible crop, RDKit parse outcomes are recorded for every
proposal, and no existing text-confirmed path has been changed automatically.
