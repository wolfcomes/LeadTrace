# PfPKG 004 Edge completion — 2026-09-20

User authorized completion of the reviewed missing-Edge inventory. Applied only
to the existing preview workspace `27bf4ad2-187d-429c-b18b-3d3cf79c3eba`, on instance
`7a1f3f21-3c30-4647-b4b9-a8dbbec8c773`. Original version 391; final version 551.

## Delivered graph

| Lineage | Members | New draft Edges | Meaning / evidence |
| --- | ---: | ---: | --- |
| 合成转化补充 · Scheme 3–5 | 14 | 9 | Source-labelled transformations; original Scheme regions, role supports |
| R1 SAR · 吡啶取代（母体 1 比较） | 15 | 14 | Baseline structural/SAR comparisons; Table 1, contextual |
| R2 SAR · 吡咯碳位取代（母体 1 比较） | 10 | 9 | Baseline structural/SAR comparisons; Table 2, contextual |
| R3 SAR · 哌啶环变化（母体 1 比较） | 12 | 11 | Baseline structural/SAR comparisons; Table 3, contextual |
| R4 SAR · 吡咯氮取代（母体 1 比较） | 2 | 1 | Baseline structural/SAR comparison; Table 4, contextual |
| R5 SAR · 芳基变化（母体 1 比较） | 4 | 3 | Baseline structural/SAR comparisons; Table 5, contextual |

The original Lineage (11 members, six Edges) remains unchanged. Final counts:
44 compounds, 44 structures, 44 structure locators, 279 Activities, seven Lineages,
68 membership records (44 unique compounds), 53 Edges, 21 Evidence records and
53 Edge–Evidence links. Added six Lineages, 57 memberships, 47 Edges, three Scheme
Evidence records, and 47 links: 160 version-checked editor API operations.

The pair 1→21 appears once in the synthetic Lineage and once in the R2 comparison
Lineage with distinct explicit meanings. There are 52 unique directed endpoint
pairs overall, not 53 unique chemical transformations. No duplicate endpoints
within a Lineage were introduced.

## Scientific interpretation

All new Edge summaries identify automated AI origin and pending human review.
All new Edge statuses are `draft`; no reviewer confirmation or submission was
performed. The comparison type is `sar_baseline_comparison`; compound 1 is the
baseline and comparison children use `unspecified` member roles. These arrows do
not assert direct synthesis, chronology, or increased potency.

The nine source-based transformations are 12a→16, 12b→17, 18a→19a, 18b→19b,
1→21, 21→22, 21→23, 22→25 and 23→26. Scheme 5 and the new 23→26 summary preserve
the prose numbering conflict (“nitrile analog 22” vs Scheme's nitrile 23).
R3 summaries for 38–41 preserve the prose position/label conflict and racemate
identity. Existing compound descriptions and the 11a N-Boc/N-Cbz warning remain.

New Evidence is cropped by normalized source-PDF regions: Scheme 3 and Scheme 4
on PDF p4, Scheme 5 on PDF p5. All 47 new links refer to visual evidence with
`quoted_text=null`; no text quotation was manufactured to satisfy a validator.
Synthetic evidence supports the source transformation; table evidence is labelled
contextual for AI-proposed SAR comparisons. Original table Evidence was reused.

Deferred paths from the audit remain deferred: 58→59→20, 11g→14→27, 11g→62→28,
11a→18a identity conflict, and the separately discussed 61→24 multistep route.
Completion is scoped to the audited nine transformations and 38 comparisons,
not all synthesis intermediates or every possible pair in the full paper.

## Execution and verification

- `prepare_plan.py` checks PDF identity, endpoint mapping, missing-pair status,
  member roles, duplicates and API request schemas before producing the plan.
- `append_reviewed_edges.py` uses the original protected preview-reviewer account,
  confirms preview identity and expected version, then records each response ID
  in an fsynced operation journal. It does not replace a workspace or rerun the
  legacy import. Editing endpoints attribute the change to preview-reviewer;
  every new description/summary records AI origin rather than human approval.
- `verify_after.py` checks exact plan-to-database correspondence, all 47 draft
  edges and Evidence links/roles, membership and expected counts. It verifies every
  original record is preserved, compound/structure/locator/Activity/section content
  is exactly unchanged, and all six other full scientific snapshot hashes match.
- Live browser acceptance traverses all six added Lineages and all 47 Edges,
  verifies graph counts, draft status, complete summary and linked Evidence role,
  renders Scheme 3/4/5 and Table 1 PDF regions, and checks compound 51 still has
  21 Activity rows. Scientific browser writes and page errors must both be zero.

## Artifacts and safe continuation

External artifact root:
`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/edge-coverage-repair-20260920`

- `append-plan.json`: exact reviewed completion plan.
- `append-operations.jsonl`: 160 sequential operations and their created IDs.
- `append-result.json`: resulting version and ID mappings.
- `004-before.json`, `004-after.json`, `before-workspaces.json`: science snapshots.
- `verification.json`: database comparison and preservation checks.
- `browser/verification.json`, screenshots: live user-interface acceptance.
- `verify_after.py` and `browser_verify.mjs`: read-only science verification.

Do not replay append/construction scripts as a routine restart. Existing preview
runs at http://10.21.53.251:18080/review/tasks with the same original credentials.
No frontend rebuild, schema change or backend restart was required for this data
completion. Historical audit files intentionally retain their before-state counts;
this document and the completion artifacts describe the new state.
