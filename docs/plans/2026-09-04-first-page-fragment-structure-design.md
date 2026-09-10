# First Page Fragment Structure Review

## Goal

Provide a chemistry-first review view for the first 20 Papers in manifest order, centered on PDF image interpretation and fragment-level SMILES reasoning before showing text-derived modification relationships.

## Design

The existing pipeline snapshots remain read-only. A new derived snapshot will select the first 20 manifest Papers and join their PDF structure crops, DECIMER proposals, auto-filled review items, and Paper metadata. Each image candidate will be represented as a fragment-aware review record with:

- source crop and exact PDF page/location;
- observed scope (`fragment_or_series`, `complete_molecule_candidate`, or `unknown`);
- scaffold/fragment/attachment-point fields, preserving R/R1/R2/R3 notation when endpoints are not resolved;
- proposed raw/canonical SMILES and RDKit syntax status;
- separate accuracy gates for image localization, fragment recognition, attachment/connectivity reasoning, and full-molecule SMILES;
- evidence-linked Paper/entry IDs and a human review status.

Full parent/derived SMILES remain empty unless supported by an exact SI or manually confirmed source. DECIMER output remains a proposal and is never promoted to confirmed structure by this snapshot.

The Dashboard will expose a first-page structure review panel beneath the project overview. It will summarize the 20 Papers, 31 current image candidates, candidate-level RDKit status, fragment-versus-complete interpretation, and unresolved image candidates. Selecting a record shows the crop first, then the structured reasoning and only afterward the linked SAR/text information.

## Accuracy Model

`rdkit_valid` means only that the proposal parses. It is not chemical accuracy. The UI uses these distinct states:

- `syntax_valid`: RDKit can parse the proposal;
- `suspicious_needs_review`: parses but contains signals such as metals, excessive components, or unusual length;
- `invalid_needs_review`: does not parse;
- `fragment_only`: the source image is treated as a partial scaffold/series representation and must not be evaluated as a whole-molecule SMILES;
- `human_confirmed`: reserved for future reviewer confirmation.

## Safety and Persistence

The derived snapshot is written under `09_paper_review/auto_fill/`. Existing PDFs, source CSVs, and confirmed structure files are not modified. The existing Paper review override API remains the only path for human edits.

## Verification

Tests will cover first-page selection, deterministic candidate joining, accuracy-state classification, Dashboard API exposure, and the existing full test suite. The generated snapshot will be checked for 20 unique Papers, 31 candidate records, no duplicate candidate IDs, and no automatic confirmed structures.
