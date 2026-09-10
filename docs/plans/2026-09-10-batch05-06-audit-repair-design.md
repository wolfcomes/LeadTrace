# Batch05 / Batch06 Audit Repair Design

**Date:** 2026-09-10

## Goal

Repair the source-confirmation boundary exposed by the Batch05 / Batch06
audit without discarding useful two-dimensional connectivity data.  A record
may remain `structure_confirmed` only when the cited source supports one
unique complete molecular graph, including every experimentally defined
stereocenter.

## Scope

The repair has four independently auditable parts:

1. Withdraw 112 Batch05 records for which the reviewed sources describe a
   racemate/stereoisomer mixture or do not define one unique stereochemical
   molecule.
2. Replace 28 `0eb39d3b45ae` source-table graphs with source-located,
   R-configured isomeric SMILES.  The article explicitly identifies these
   compounds with `(R)` experimental names; compounds 11 and 12 retain their
   separately defined indoline stereocenters. Seven isolated records (`3c`,
   `3e`-`3j`) are named only as `Enantiomer II`, without an absolute R/S
   assignment, and therefore join the exclusion set instead of receiving an
   inferred configuration.
3. Withdraw Batch06 compounds `2a98b0589a08 / 12` and `15`, which the article
   explicitly reports as pairs of diastereomers.
4. Correct aggregate evidence metadata: `figure_explicit` is supported
   evidence, and the annotation's reviewed evidence sentence must not be
   silently replaced by an unrelated sentence from the same page.

The remaining 59 RDKit risk hits (37 Batch05 and 22 Batch06) are deliberately
outside this publication repair because their source-level classification is
not complete.  They remain visible for the next review pass.

## Data model

Reviewed exclusions are keyed by immutable `work_row_id`, not merely by a
compound label.  Each exclusion stores a paper/label-specific reason and a
source locator.  The source graph remains in `compound_structure_work.csv` as
an auditable rejected candidate while the corresponding row is removed from
`confirmed_compound_structures.csv`.

Reviewed stereochemical replacements are new accepted work rows with
`replacement_decision=explicit_replace`.  Their graph connectivity is taken
from the exact machine-readable source row; only the single source-defined
but omitted stereocenter is enumerated.  RDKit must assign that center CIP
`R`, and all pre-existing assigned stereocenters must be preserved.

The aggregate is then rebuilt from the authoritative confirmed-structure
table.  With this sequence, Dashboard molecule images continue to be redrawn
from confirmed SMILES, while unresolved compounds show `--` instead of an
arbitrary stereoisomer.

## Evidence handling

`text_explicit`, `figure_explicit`, and `human_confirmed` relations are all
supported statuses.  Evidence strength will preserve the distinction:

```text
text_explicit   -> text_explicit
figure_explicit -> figure_explicit
human_confirmed -> human_confirmed
unresolved      -> unresolved_context
```

The annotation evidence sentence remains authoritative.  Page-level evidence
matching may be retained only as separately named contextual information; it
must not overwrite the reviewed annotation statement in the current CSV
schema.

## Failure safety

The publisher validates the complete requested label set before writing.  It
rejects missing or duplicate source rows, verifies current immutable work-row
IDs, checks CIP assignments, and uses the existing atomic publication lock.
Aggregate rebuilding occurs only after structure publication succeeds.

## Verification

Tests must cover the exact 112/28/2 decision boundaries, R-CIP reconstruction,
preservation of existing stereocenters, idempotent publication, evidence
strength mapping, and non-substitution of annotation evidence.  Final checks
include the full lineage/structure suite, aggregate invariants, exact batch
counts, Dashboard data tests, live HTTP/API acceptance, and representative
molecule-image suppression/reconstruction checks.

This workspace is not a Git repository, so the design cannot be committed;
the document and all repair artifacts remain in the project tree.
