# DeepSeek revision prompt and feedback template

版本 `deepseek-supervised-v2`。以下为离线指导格式，不宣称符合正式 Evaluation schema。反馈 ID 可以随实际输入记录进入候选来源链；对工作区的正式 Evaluation 应由模块绑定真实快照生成。

监督者先填写以下反馈正文，再将末尾提示词交给 harness：

```text
Feedback ID: {{FEEDBACK_ID}}
Parent candidate ID: {{PARENT_CANDIDATE_ID}}
Parent file SHA-256: {{PARENT_FILE_SHA256}}
Source PDF SHA-256: {{SOURCE_SHA256}}
Decision: needs_revision
Reviewer identity/type: {{ACTUAL_REVIEWER_AND_AI_OR_HUMAN}}

Issue: {{CHECK_LABEL}}
Observed: {{CONCRETE_ACTUAL_DEFECT}}
Entities and scope: {{REFS_AND_ENTIRE_SERIES_OR_TABLE_AFFECTED}}
Source: {{PDF_PAGE_TABLE_ROW_AND_LOCAL_CROP}}
Required correction: {{WHAT_MUST_CHANGE}}
Verification evidence: {{SOURCE_COMPARISON_AND_OUTPUTS_REQUIRED}}
Preserve: {{UNAFFECTED_SECTIONS}}
Uncertainty: {{UNRESOLVED_SOURCE_CONFLICT_OR_NONE}}

Repeat the issue block for additional issues. Do not include guessed source
answers. If the reviewer and candidate disagree, re-open the original source.
```

可复用修订提示词：

```text
Revise {{PARENT_CANDIDATE_PATH}} into a NEW candidate at {{NEW_OUTPUT_PATH}},
ID {{NEW_CANDIDATE_ID}}, following input.json and {{FEEDBACK_PATH}}.
Check the parent file SHA-256 and source identity before editing, including the
external manifest/catalogue mapping and actual source byte size. A source
identity mismatch is not repaired by renaming a candidate or changing only its
DOI. Stop for corrected inputs. For label-only repairs, assert every other payload
field and every ref/ordering is unchanged and rerun compound coverage. Read the
same extraction guide and quality checklist as the parent plus supplied changes.
Preserve the parent and all previous reports. Use the actual parent_candidate_id
and supplied input_evaluation_ids; do not fabricate application/snapshot IDs.

Address every feedback item and inspect the full affected series/table. An
example of one bad graph does not mean only that graph needs repair. For ring
closure collisions, rebuild correct connectivity and compare original drawings;
canonicalization or formula agreement is not a fix. For crop corrections,
inspect each actual final PNG and every affected compound's own source set.

Keep unaffected scientific sections unchanged unless source inspection reveals
another concrete error; report any additional change and its evidence. If a
host reference value conflicts, zoom the PDF and resolve it rather than copy
the feedback blindly. Do not manufacture missing source data or Evidence.

Deliver the new complete candidate, updated quality-record.json/review-notes.md,
and change-log.md mapping each feedback ID/issue to changed refs, source evidence,
real checks and unresolved items. Include before/after graph checks where needed.
Reset supervisor_preview_gate to not_reviewed for the new candidate; do not copy
the parent's clearance or fill in supervisor checks or delivery receipts yourself.
Run {{VALIDATION_COMMAND}} and save the result. The supervisor will compare
parent and child independently. Finish within {{RUN_BUDGET_DESCRIPTION}};
if unresolved, preserve work and explain the exact remaining blocker.
```
