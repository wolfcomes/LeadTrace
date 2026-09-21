# Lineage point/structure modes and zoom — 2026-09-20

Implemented the requested UI revision in the existing ai-prefill-tools worktree.
The graph now opens in compact point/line mode, with labelled 42px circle nodes.
An accessible two-button mode selector switches to the existing 220 × 160 RDKit
structure cards. The same compounds and Edges appear in both modes, with actual
canvas Edge selection leading to the existing main-pane detail view.

Modes use their own node spacing and retain independent zoom/pan while switching
within the same graph. Graph membership/relationship changes invalidate the saved
views. Opening Edge detail and returning keeps the selected mode. A fresh page
starts in point mode. Point mode does not load graph depiction images; endpoint
detail still loads structures as before.

Zoom buttons now multiply/divide scale by 1.5 (previously 1.25). Wheel sensitivity
is 3 (previously 0.15). This is calibrated against Cytoscape 3.34.3's discrete-device
normalization: the intermediate setting 0.65 produced only 3% initial zoom per
100px wheel event. The final setting produces roughly 15% initially and 9% after
discrete-device detection in the Chromium test, with the existing min/max bounds.
Trackpads and other devices remain dependent on event size/frequency.

## Verification

- 23 frontend test files / 112 tests pass, including the new default-mode and
  mode-preserving Edge navigation test (failed before implementation).
- Type checking and production Vite build pass; existing dependency/bundle warnings
  remain. `git diff --check` passes.
- Live browser checks cover actual circle/card rendering, default mode, initial
  and normalized wheel zoom and reverse direction, independent mode viewports,
  canvas Edge clicks in both modes, Edge detail and PDF Evidence, browser history,
  direct links, mobile width, failed images and an Edge without linked Evidence.
- Layout checks include PfPKG R1, R3, synthesis supplement and paper 007's 54 nodes.
- Seven full scientific snapshots are compared with fresh pre-change baselines.
  No scientific writes are needed for this revision.

Artifacts and reproducible scripts:
`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/lineage-view-modes-20260920`

`browser_verify.mjs` reads protected credentials through the existing descriptor,
then writes `browser/verification.json` and screenshots. `verify_unchanged.py` uses
the worktree Python environment and writes `scientific-verification.json`.

Same LAN preview: `http://10.21.53.251:18080/review/tasks`.

## Classification assessment

The separate `lineage-sar-synthesis-assessment-2026-09-20.md` records the dataset
review and recommendation: explicit semantic category on each Edge, aggregated
SAR/synthesis/mixed/unclassified summaries on Lineages, retaining evidence and
review state as separate dimensions. Existing paper 009 includes mixed relations;
PfPKG has both synthesis and SAR Edges for the same compound pair. No semantic
category migration or automatic scientific reclassification was applied here.
