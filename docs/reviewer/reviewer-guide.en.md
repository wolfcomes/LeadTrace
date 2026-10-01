# Reviewer guide

Version: 2026-09-28

> Generated from `leadtrace/frontend/src/review/help/reviewer-guide.json`. Edit that source and run `python leadtrace/ops/reviewer/render_guide.py`.

## Start with identity and coverage

Verify title, DOI and PDF. Include every numbered or labelled Compound with a determinable structure, including starting materials, intermediates and controls without activity data. Examples illustrate format and are not paper facts.

## Compound and Structure

Keep source labels such as 24 or 7a; display name is optional. Each Compound has one Structure. Verify connectivity, substitution and stereochemistry after entering SMILES or using the structure editor. Explain unresolved identity rather than inventing a structure.

## Article starting points and prioritized compounds

On the article information page, link a Compound and existing Evidence, record its study-start or paper-prioritized role, study/series scope and author rationale. Multiple compounds and both roles are allowed. Save source support in the Evidence library first; cards retain the PDF page and quotation. A study start is not every synthesis reagent; a prioritized compound is not every terminal or the lowest IC50. Draft, confirmed and unresolved states remain visible. Viewing never confirms; unrecorded does not mean absent. Recheck after changing identity, rationale or source, and explicitly clear resolved verification hints.

## Organize Lineages

SAR describes design and structural comparison; synthesis describes chemical routes. Never connect compounds solely by label order. Keep one logical route together; separate independent routes. Root starts a route, intermediate is internal, terminal ends it. Terminal does not automatically mean best activity or nominated lead; record author starting points and prioritized compounds in article annotations. Do not force isolated controls into a lineage: document their purpose and exclusion in the Compound description.

## Graph, Compound and Edge views

Switch between three tabs. Add Node selects an existing Compound from this paper; create missing Compounds on the compound page first. Add Edge selects source then target before opening the relationship form. Drag nodes or diamond control handles and Save layout. Point and structure modes save separately. Reload layout discards unsaved layout in that mode. Full forms remain available.

## Edge and Evidence

Verify relationship type, endpoints and modification summary. Fictional format example: Me → OMe, comparing lipophilicity; relationship inferred from structures, not explicitly stated by the authors. Distinguish source support from inference; table order is not optimization order. Evidence retains exact quotations, actual PDF page and region. supports/contradicts/contextual describe evidence roles. Viewing never changes draft to reviewer_confirmed.

## Activity format

Fictional example: Assay = human MAO-B inhibition; Metric = IC50; Operator = <; Value = 10; Unit = nM; Context records assay conditions. Do not put <10 nM entirely in Value or combine different assays. Preserve units and qualifiers.

## Abstract and PDB

Store the original abstract with provenance, not an AI summary. PDB IDs support legacy four-character and extended pdb_ formats. Three-character ligand codes such as ATP are not PDB IDs. Distinguish this-work structures, cited structures and unknown usage; record page and context. Pair with a Compound only when explicit in the source. Empty means unrecorded, not proven absent.

## Viewed, needs verification and submission

Viewing is recorded only for Compound and Lineage groups. Explicitly select a Compound or Lineage (including opening its Edge details); background loading or viewing the graph does not mark every group. A Compound includes its fields, structure, source images, activities and linked evidence. A Lineage includes members, their Compound content, edges and linked evidence. Related edits invalidate the affected groups; unrelated groups remain unchanged. Groups can be marked unread. Only these two counts are shown; Structures, Activities, Edges and Evidence have no separate viewing checkmarks. Article information retains its manual section confirmation. Unassigned Evidence remains in the evidence library and is covered by the final whole-paper confirmation. Historical narrow-scope receipts do not establish group viewing: reopen the current group. Text accompanies colors. Viewed is not scientific approval, never clears verification hints, and never confirms Structures or Edges. Empty sections still need an explicit not-reported disposition. Final human confirmation, submission and Admin approval remain required.

## Conflicts and saving

Scientific edits use the Workspace version; on conflict reload and reconcile instead of overwriting others. Layout has its own revision; viewing does not increment scientific versions. Keep hints and drafts when unresolved; never confirm merely to pass submission checks.

## Group abbreviation reference

| Symbol | Meaning | Check |
|---|---|---|
| Me | Methyl | –CH₃; OMe has an additional oxygen linkage. |
| Et | Ethyl | –CH₂CH₃ |
| n-Pr / i-Pr | n-Propyl / isopropyl | –CH₂CH₂CH₃ / –CH(CH₃)₂; attachment differs. |
| n-Bu / i-Bu / s-Bu / t-Bu | Butyl isomers | n-Butyl, isobutyl, sec-butyl, tert-butyl; not interchangeable. |
| Ph | Phenyl | –C₆H₅; attached directly through the aromatic ring. |
| Bn | Benzyl | –CH₂C₆H₅; one methylene more than Ph. |
| Be | Beryllium (element symbol) | Not a standard benzyl or phenyl abbreviation. Check the source definition or typography; do not silently replace with Bn/Ph. |
| OMe / OEt / OBn | Methoxy / ethoxy / benzyloxy | Attached through O; distinct from Me/Et/Bn. |
| Ac | Acetyl | –C(=O)CH₃; OAc is acetoxy. Preserve the attachment atom. |
| Boc | tert-Butoxycarbonyl | Common amine protecting group; preserve the actual attachment. |
| Cbz / Z | Benzyloxycarbonyl | Protecting group; not Bn. |
| Fmoc | Fluorenylmethoxycarbonyl | Protecting group; verify attachment in the drawing. |
| Ts / Ms / Tf | Tosyl / mesyl / triflyl | Distinguish from OTs/OMs/OTf and distinguish salts from covalent groups. |
| Ar / HetAr | Aryl / heteroaryl (generic) | Not a unique structure; resolve the definition and substitution positions. |
| R / R¹ / R² | Variable substituents | Expand only when assigned in the substituent table for that compound. |
| o- / m- / p- | Ortho / meta / para | Usually 1,2 / 1,3 / 1,4 on disubstituted benzene; verify numbering. |

PDB format reference: https://www.rcsb.org/docs/general-help/identifiers-in-pdb
