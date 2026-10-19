# Reviewer activity comparison

Approved scope: a read-only Activity comparison tab between Compounds and Lineages.
One row per Compound, including compounds with no Activity. Columns use exact assay
name, metric, unit and context; never infer equivalence, convert units, average or
discard multiple observations. Preserve decimal strings, operators and review hints.
Search labels/names, select measurement columns, sort Compound identifiers naturally.
Click a Compound or individual measurement to open its editor; an explicit return
button retains table filters/order/scroll and reloads saved changes. Browsing the
matrix does not record views or scientific confirmations. Pending editor work must
not be silently discarded by navigation.

A single read-only authorized workspace query returns compounds, activities and a
consistent workspace version. Reviewer assignment/Admin read permissions follow
existing draft policy. No schema changes. Load failures show retry, never missing
measurements; no data from a different workspace or an obsolete request is rendered.

Use the existing Activity editor for focused records and original review-hint
presentation. Add bilingual labels, regression coverage and a synthetic browser test.
