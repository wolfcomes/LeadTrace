# Molecular Lineage graph and in-page Edge detail verification — 2026-09-20

The existing review preview now displays RDKit molecule depictions in Cytoscape
nodes. Clicking a canvas Edge replaces the main pane with the selected relationship,
two endpoint molecule cards, structure status, description/SMILES, and linked
Evidence, including the existing source-PDF region viewer. Each endpoint links to
its compound's structure, source images and Activity records.

## Interaction and layout

- Fixed 220 × 160 molecule cards, numbered labels and highlighted Root borders.
- Single-baseline star comparisons use a concentric layout; other graphs use a
  force layout with node dimensions and spacing included in layout calculations.
- Initial/readable zoom has a 65% floor. Large graphs intentionally require
  panning or compound lookup; full overview can shrink structures substantially.
  It is for topology, not reading atom labels. Zoom buttons, wheel zoom, compound
  locator and expanded canvas provide ways to inspect individual structures.
- Clicking an Edge or its accessible “查看关系详情” button opens its detail pane.
  “返回关系图” retains the graph's zoom/pan. URL entity selection supports direct
  links and browser back/forward. Switching Lineage from a directly opened Edge
  also renders the newly selected graph.
- SAR baseline endpoints are captioned 比较基线 / 被比较化合物. The Edge's relation
  type and original explanation remain visible; arrows do not imply synthesis or
  improved potency. Existing edit, review-status and Evidence controls remain.
- Missing/failed depictions have explicit fallback text and compound-detail links.
  Unlinked Evidence is permitted and shown honestly, without suppressing the Edge.
- Structure metadata requests are cached within the mounted workspace editor,
  limited to four concurrent reads, and prioritize the visible Lineage over older
  queued members. Workspace changes discard stale results. Large graphs load
  progressively; first load is not instantaneous.

## Verification

- `npm test -- --reporter=dot`: **23 files, 111 tests passed**.
- `npm run build`: Vue/TypeScript checking and Vite production build passed.
  Existing dependency directives and bundle-size warnings remain.
- `git diff --check`: passed.
- Navigation tests cover graph selection, correct endpoints/Evidence, direct Edge
  URLs, missing structures, failed images, browser history and admin read-only
  controls. Cache tests cover bounded concurrency, stale responses, cache reuse
  and visible-Lineage priority (the added priority case failed before the fix).
- Live Chromium acceptance used the authenticated LAN preview. It measured zero
  node bounding-box overlaps for PfPKG R1 (15 nodes / 14 Edges), R3 (12 / 11),
  Scheme 3–5 supplement (14 / 9), and paper 007 (54 / 44).
- An actual mouse click at the canvas midpoint of R1 `1 → 12a` opened its detail;
  both endpoint images and the Table 1 PDF evidence region loaded. Return/history,
  locator, expanded canvas, direct Edge links followed by Lineage switching,
  390px mobile width, paper 007's Edge without linked Evidence, and intercepted
  image failures were exercised. No application page errors or scientific writes.
- Seven complete canonical scientific snapshot hashes are unchanged. PfPKG stays
  at workspace version **551**, with **44 compounds / 279 Activities / 7 Lineages /
  53 Edges**. The six other workspaces stay at version **2**.

## Preview and reproducible artifacts

LAN: `http://10.21.53.251:18080/review/tasks`

Instance: `7a1f3f21-3c30-4647-b4b9-a8dbbec8c773`.
Frontend is served from this worktree's `leadtrace/frontend/dist`; no backend
restart or migration was required. Existing accounts remain in the protected
credential file referenced by the live descriptor. Do not copy credentials here.

Artifact root:
`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/molecular-lineage-ui-20260920`

- `browser_verify.mjs`: read-only LAN acceptance and screenshots, reads credentials
  from the descriptor without logging them. Run with `node browser_verify.mjs`.
- `browser/verification.json`: browser results and measured layouts.
- `browser/*.png`: overview, reading view, Edge detail/evidence and mobile captures.
- `before-workspaces.json`: pre-UI scientific snapshots.
- `verify_unchanged.py`, `scientific-verification.json`: compare current snapshots
  with captured baselines; run using the worktree's `.venv/bin/python`.

Do not replay compound/Edge append scripts for UI validation. Historical UI
scripts with the removed Evidence/Activity tab remain obsolete. Data conflicts
previously recorded in the Edge-completion report are not resolved by this UI.
