# Legacy Dashboard Split Source Paths Design

## Goal

Update the legacy Dashboard's displayed Paper source locations after the PDF
corpus was reorganized into `source_pdfs/volume<number> issue<number>/`
directories. The change is display-only: it does not serve PDFs, modify source
PDFs, or rewrite pipeline CSV/JSON snapshots.

## Current State

The pipeline manifest and document index still contain the earlier source
folder names and absolute PDF paths. All 672 Paper records can be matched by
filename to the reorganized corpus. The corpus contains 648 unique PDF files;
24 additional Paper records intentionally reuse one of those files. No PDF is
unmatched or ambiguous in the current corpus.

## Approach

At runtime, the Dashboard builds an index of PDF files found exactly one level
below `source_pdfs/`. Only directories named `volume<number> issue<number>` are
eligible. A Paper is resolved by the existing `filename` field.

When exactly one eligible file has that filename, the API payload replaces:

- `source_folder` with the issue directory name, such as `volume67 issue1`;
- `source_pdf` with a project-relative POSIX path, such as
  `source_pdfs/volume67 issue1/example.pdf`.

The API never exposes the local absolute filesystem path. If no file or more
than one file matches, the original snapshot values remain unchanged so the
Dashboard cannot silently attach a Paper to the wrong source.

The index is shared for the lifetime of the server process. Re-splitting the
corpus therefore requires a Dashboard restart, which matches the existing
snapshot-oriented service model.

## Data Integrity

Filename is the identity bridge because every current manifest filename has a
unique physical match. File size is not used to select a path: 23 manifest
records differ from the current file size, and this task only updates displayed
locations. No scientific record, review override, confirmed entry, or source
asset is changed.

## Affected Surfaces

The normalized location is applied where the Dashboard assembles its canonical
Paper records. Paper list and Paper detail responses therefore stay consistent,
and the existing UI automatically displays the new issue directory and relative
path. OCSR and other evidence records retain their own historical provenance
fields unless they are derived from the canonical Paper record.

## Testing

Tests use a temporary source directory and cover:

- a unique filename match;
- two Paper records sharing one physical PDF;
- a missing filename falling back to the snapshot values;
- duplicate physical filenames falling back rather than choosing arbitrarily;
- list and detail payloads displaying the same normalized source location.

After the focused tests pass, run the full legacy Dashboard suite, compile the
Python server, validate the JavaScript syntax, restart the read-only service on
`127.0.0.1:8765`, and check representative Papers from volume 67 and volume 68.
