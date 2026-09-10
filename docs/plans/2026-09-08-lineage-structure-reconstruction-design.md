# Lineage Structure Reconstruction Design

## Goal

Resolve complete molecular structures for the 47 Papers already represented in
the compound-lineage dataset. The workflow must parse structure figures, expand
shared scaffolds and R-group tables, reconstruct numbered compounds, validate
the resulting molecular graphs with RDKit, and bind confirmed structures back
to the existing Paper-local compound entities.

The first processing priority is the 28 Papers with no structures or partial
structure coverage. Remaining gaps in the other 19 Papers follow after the
workflow has been calibrated.

## Confirmation Model

Use one externally visible final state:

```text
structure_confirmed
```

Direct SI structures and reconstructed structures share this state. Their
different provenance remains visible through source fields and the reconstruction
audit, rather than through additional Pipeline states.

RDKit validity alone is not confirmation. A structure is confirmed only when:

- the Paper-local compound label is mapped unambiguously;
- the result is a complete molecular graph without unresolved R groups, dummy
  atoms, or attachment-point markers;
- RDKit parses and canonicalizes the structure without a valence failure;
- stereochemistry is retained only when it is supported by the source;
- source file and page, table, figure, or record locator are retained;
- an RDKit rendering agrees with the source structure or exact machine-readable
  SI record.

Only a lineage edge whose parent and derived entities both satisfy these rules
is eligible to display a complete molecular pair.

## Source Priority

Resolve each numbered compound from the strongest available source:

1. Machine-readable SDF, MOL, SMILES CSV, or spreadsheet with an exact compound
   label mapping.
2. SI PDF table or scheme containing a complete numbered structure.
3. SI or article figure containing a shared scaffold plus explicit R-group rows.
4. Isolated complete-structure, scaffold, or fragment crops processed by OCSR.
5. Otherwise retain the compound as unresolved and record the failure reason.

File extensions do not establish chemical content. Each CSV, spreadsheet, ZIP,
or PDB attachment must be inspected before it is classified as a structure
source. Page-level OCSR output remains a proposal and is never promoted solely
because RDKit can parse it.

## Data Files

Keep the new data layer compact.

### `structure_source_manifest.csv`

One row per discovered source attachment or source document. It records Paper,
DOI, source file, URL or local path, media type, content classification, checksum,
download status, and inspection status.

### `compound_structure_work.csv`

One row per compound structure candidate. It records the Paper and compound
label, candidate type, raw and canonical SMILES, scaffold representation,
R-group assignments, attachment mapping, source locator, RDKit results,
stereochemistry status, visual comparison status, review note, and disposition.

Scaffold and R-group details may be encoded as stable JSON values in dedicated
columns so single-site and multi-site reconstructions use the same row model.

### `confirmed_compound_structures.csv`

One row per confirmed Paper-local compound. It records canonical isomeric
SMILES, confirmation state, provenance, source locator, reconstruction method,
RDKit version, and the accepted work-row identifier. This is the sole new
authoritative structure output.

The lineage builder copies confirmed values into `compound_entities.csv` using:

```text
canonical_smiles=<canonical isomeric SMILES>
structure_status=complete_structure_resolved
structure_review_status=structure_confirmed
```

## Processing Flow

### Source Discovery And Parsing

Query ACS Figshare by DOI, persist the article and file metadata, and download
eligible attachments. Inspect structured files for compound-label and structure
columns. Extract archives into a controlled per-Paper source directory and retain
their checksums and original member paths.

### Figure And Table Interpretation

Render relevant PDF pages and identify complete structures, shared scaffolds,
variable sites, R-group columns, compound-number rows, and stereochemical marks.
Store each crop as evidence, but never use the crop itself as the final molecule
display.

### Reconstruction

Represent attachment points with atom-mapped dummy atoms while the candidate is
being assembled. Match each R-group assignment to a named scaffold site, join
the fragments using RDKit graph operations, remove resolved dummy atoms, sanitize
the molecule, and generate canonical isomeric SMILES. Multi-site compounds must
resolve every attachment before they can proceed.

### Validation And Binding

Validation checks parsing, sanitization, valence, unresolved atoms, disconnected
components, duplicate labels, source stereochemistry, and deterministic
canonicalization. The accepted molecule is rendered with RDKit and compared with
the source graph. Confirmed structures are then joined to the existing entity by
`paper_id` and normalized compound label; lineage pair eligibility is recalculated
after the join.

## Error Handling

- Ambiguous or duplicate compound labels stay in the work table and never
  overwrite an entity.
- Salts, solvates, and mixtures are not silently stripped. A parent component
  may be selected only when the source clearly identifies the intended compound,
  and the transformation is recorded.
- Missing attachment sites, mismatched attachment maps, invalid valence, and
  unsupported stereochemistry produce explicit rejection reasons.
- Existing confirmed structures are preserved unless a new candidate is both
  source-backed and explicitly selected as a replacement.
- Downloads and generated CSV files are written atomically so partial runs do
  not corrupt confirmed data.

## Calibration And Scaling

Start with three to five zero-structure Papers selected to exercise:

- exact machine-readable SI mapping;
- one-site scaffold/R-group expansion;
- multi-site scaffold/R-group expansion;
- explicit stereochemistry;
- unresolved or conflicting source evidence.

After the fixture and integration tests pass, process independent Papers in
parallel. Confirmation remains deterministic and is merged centrally to prevent
concurrent writes to the authoritative CSV files.

## Testing

Unit tests cover source classification, label normalization, SMILES cleanup,
single- and multi-site attachment, unresolved dummy atoms, invalid valence,
stereochemistry handling, salts, duplicate candidates, and atomic output.

Integration tests run a small source fixture through discovery, candidate
generation, reconstruction, confirmation, entity binding, and lineage pair
eligibility. Regression tests ensure existing confirmed entities and lineage
edges are unchanged when no stronger candidate is accepted.

## Acceptance Criteria

- Every confirmed SMILES is complete, RDKit-valid, source-traceable, and bound
  to one unambiguous Paper-local compound label.
- Every reconstructed structure records its scaffold, R-group assignments, and
  resolved attachment mapping.
- No page-level OCSR result is promoted solely because it parses.
- No unresolved R group, dummy atom, or attachment marker reaches the confirmed
  output.
- Pair-ready edges contain complete confirmed structures on both sides.
- Final molecular images are generated uniformly from confirmed SMILES with
  RDKit and never copied from article figures.
