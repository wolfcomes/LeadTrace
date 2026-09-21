# DeepSeek harness prefill experiment

User request: guide the installed DeepSeek harness to prefill several new papers
and observe quality. This uses existing offline CandidateEnvelope/Preview tools;
no product feature, production apply or deployment change is required.

Selected papers from the existing first20 baseline: 007 (C5aR1 antagonists),
009 (Juglone derivatives), 020 (VISTA inhibitors). Prior 004/005/010/013 workspaces
must remain unchanged. Independent harness working directories receive only
source PDFs, schema, guide, generic extracted text and explicit task prompts.
No credentials or database authority are supplied to the model.

1. Verify installed harness and configured model: dsh0.1.5-rc.2 / deepseek-flash.
2. Run source-based first extraction for three papers. Preserve prompts, raw
   candidates, scripts, output and validation. Require real rendered-table/image
   inspection, original structure locators, activity provenance, optional-evidence
   AI edges and explicit omissions.
3. Independently check quantities, source-table cells, structures and crop bounds.
   Record initial quality honestly; do not silently attribute host corrections
   to DeepSeek. Supply actionable feedback and preserve immutable revisions.
4. Apply technically valid, scientifically reviewable results to untouched paper
   workspaces in the current isolated Preview. Annotate uncertainties, keep draft
   state, and verify real browser display through existing LAN entrance.
5. Report coverage, errors/corrections, remaining scientific uncertainty and
   practical suitability. Preserve old four-paper versions and update handoff.

Experiment root (outside Git):
/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/deepseek-prefill-20260920

Main comparison is guided first run vs feedback revision, not a blinded benchmark.
The sample is deliberately small and cannot establish a general accuracy rate.

## Delivery

Completed with raw v1 preserved and source-based host feedback:
007 needed v2 graph reconstruction + v3 crop repair;009 needed v2 graph/crop
repair;020 needed v2 crop repair. Final105compounds,501Activity records,
166locators,89draftedges applied to three new tasks in the existing native
Preview. Old four workspaces preserved. Same LAN entrance/account passwords.

Main finding: valid SMILES and HRMS formulas did not detect nested ring-digit
collisions (67incorrect v1 molecular graphs). Require independent final
connectivity/rendered-source comparison. Final numeric/operator/ND sample checks:
206passed. See verification-deepseek-2026-09-20.md for scientific limitations,
exact candidate revisions and browser/database acceptance evidence.
