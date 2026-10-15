# Article metadata batches implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Supplement every successfully AI-prefilled production article in ascending paper order, preserving human work and genuine Reviewer approval semantics.

**Architecture:** Source-reading producer/self-check plus fresh reviewer for each frozen article-only patch; operator-only, additive, version/hash-bound draft supplement. Approved 001 becomes an explicit incremental revision of its existing workspace with unchanged published snapshot, stable science IDs and real prior receipts. No fabricated submissions or approvals. Audited AI metadata events are separated from Reviewer comparisons. Four articles per batch; verified completed articles skipped.

**Tech Stack:** Existing isolated Codex scientific adapter, Python/SQLAlchemy/PostgreSQL, existing Vue approval projection.

## Accepted user design

89 successfully AI-prefilled live papers;12 already supplemented.77 need missing fields/groups/evidence. Start001/006/016/017 then issue02 onward. User explicitly approved a supplemental revision for published001, keeping current published content until human approval. Preserve all populated scalar metadata/profile groups, exact evidence prefix, original submissions and decisions; invalidate only bibliography confirmation when additions change it. Do not reset versions or clear workspaces. No scientific data from Preview, no supervisor reading PDFs/text/crops/reasoning.

## 1. Guarded operator supplement and approved revision

Create backend app/publications/draft_metadata.py and tests/publications/test_draft_metadata.py. Enabled Admin only; lock Paper->Workspace->Task; immutable request digest/idempotency, exact snapshot hash/version/source; reject submitted/archived/removed/disabled/mismatched/active scientific jobs; additive metadata only. Existing profile groups stay exact, only absent/empty groups fill; populated PDB evidence appends only. Validate schema, pages,source hash, taxonomy/evidence. AI ChangeEvent action bibliography.ai_supplement before/after contains only changed metadata fields; AuditService event paper.article_metadata_supplement includes change_event_id,workspace_id,event_payload_sha256,source_sha256 and runtime evidence. Actor remains real Admin in audit; AI history not Reviewer impersonation. Bibliography pending, note unchanged, other sections/receipts/science unchanged; version increments, no submissions.

Approved revision: explicit allow_published_revision with expected current published version; same approved workspace/task becomes editing/assigned with version increment, real assigned Reviewer retained, current publication pointer and immutable snapshots/decisions preserved. Reject any conflicting active generation. Audit revision start; no blank generation or synthetic cloned confirmations.

Use TDD and existing publication fixture. Tests only disposable55459 article_metadata_test, serial. Test stale/no-op/idempotency/cross-paper/unauthorized/overwrite protections, partially populated groups and published-view immutability.

## 2. Reviewer comparison integration

Extend publications/comparison.py/reviewer_rounds.py with tests. Recognize audited additive AI metadata event, reverse it reliably for first-round reconstruction, then apply only its changed field/group deltas to the human comparison baseline. Keep subsequent Reviewer correction visible, prior human changes intact. Fold independent supplement comparison using existing UI shape; combine with existing technical supplements into one per phase. Audit identity/binding required; invalid events warn and never hide differences. Preserve legacy default API shape and previous supplement behavior. Approved revision-start is workflow, not human science.

## 3. Ordered scientific batches and delivery

Runtime root leadtrace-data/article-metadata-batches-20261015; frozen current source identity/bibliography/guides/schema, protected original PDF. Producer model gpt-6-astra high via existing codex sandbox adapter, fresh same-config reviewer; scope only article fields. Check exact abstracts, authoritative matched PMID/PMCID, controlled molecule types, mechanisms,target roles/species/genes,diseases,optimization goals,PDB mentions,original evidence. Report missing SI/full-inventory not reaudited; no invented facts.

Inspect final candidate/reviewer reports, deterministic validation, actual distinct sessions and all hashes. Backup encrypt/decrypt-verify and rehearse exact first-batch patch on isolated restored DB. Deliver one article transaction with fresh baseline; conflicts rebaseline/review affected metadata, never force. Publish stable operator source first; deployment for projection semantics necessary and within current task. Verify live metadata, preserved science/history/published001, reviewer UI and audit. Keep applying ordered batches with progress/handoff. No reset test against live/acceptance DB. Archive completed plan with hash and preserve worktrees.
