# LeadTrace Five-Slide Advisor Presentation Design

**Status:** Approved for implementation

**Date:** 2026-09-18 (Asia/Shanghai)

## Goal

Condense the existing 12-slide LeadTrace advisor presentation into a focused
five-slide version while preserving the user's selected original slides: 1,
3, 5, 6, and 7.

## Source PDF count

The cover will display **1,209 original papers**. This count includes PDF files
under the journal volume/issue directories in `source_pdfs/` and excludes 12
derived or review PDFs below `source_pdfs/分子修改提取_2024_JMC/`.

The 1,209 figure describes the current source corpus, not the number of papers
imported into LeadTrace or completed in the pilot. Existing references to the
20-paper isolated pilot remain evidence about validation only where relevant.

## Slide sequence

1. Original slide 1: LeadTrace positioning and current source-corpus scale.
2. Original slide 3: the trustworthy knowledge-production thesis.
3. Original slide 5: the governed end-to-end workflow.
4. Original slide 6: human–AI responsibility and race-safe application.
5. Original slide 7: the real scientific review workspace.

All slide footers and section labels will be renumbered as a continuous
five-slide presentation. Removed slides and their references will not remain in
the generated PowerPoint, PDF, contact sheet, manifest, README, or speaking
notes.

## Cover metrics

The cover metrics will be:

- `1209 篇` — current original-paper corpus;
- `6 类 = 0` — integrity anomalies in the isolated pilot; and
- `766 项` — backend and frontend automated tests passed in the recorded pilot
  verification.

The first metric will be labeled as the current source corpus. The latter two
will be labeled as pilot validation evidence so the scopes cannot be confused.

## Deliverables and verification

The existing deliverable filenames remain unchanged so users do not have to
find a new deck. The generator and verifier will be updated to require exactly
five HTML slides, five rendered PNGs, five PowerPoint slides, and five PDF
pages. Source/render/package SHA-256 consistency checks remain mandatory.

The final contact sheet will use a compact five-slide arrangement. The speaking
notes will be rewritten for a roughly five-minute report, with one section per
retained slide.
