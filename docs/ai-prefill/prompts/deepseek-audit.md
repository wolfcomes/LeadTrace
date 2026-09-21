# 独立源文审查提示词 — deepseek-supervised-v2

操作者用新 harness 会话；不要继承提取者解释或已知科学答案。先核验外部 task/source 身份；监督者被要求不读原文时只读取此审查的产物。建议两阶段，A 的目录中不提供候选，避免先看答案构造分母。

## 阶段 A：只看来源

```text
Audit input.json against source-identity-check.json and the actual PDF title/DOI.
Read the supplied PDF only for scientific facts. Use authorized local tools;
no credentials, databases, Preview writes, dependencies, subagents or other jobs.
Follow quality-audit-protocol.md. Save compound-inventory.json in CompoundInventory
v1 BEFORE candidate access. Do not add title to SourceIdentity or summary/
partition/feedback fields to CompoundInventory; put them in a separate sidecar. List actual labels with source locations and scope;
main narrative/SAR/controls required, Methods-only forms retained as route details.
Do not infer contiguous label ranges. Uncertain structures do not remove required
labels. Separately inventory principal activity-table cells and SAR/synthesis
relations. Mark non-exhaustive denominators unknown. Save early and stop for
supervisor handoff; no candidate generation in this stage.
```

## 阶段 B：读取冻结清单与候选

```text
Verify the frozen inventory hash and the exact candidate file hash in input.json.
Compare candidates against the inventory; do not rewrite it to match the candidate.
If the inventory itself is wrong, record a new revision and reasons separately.
Use the predefined Activity indexes and additional high-risk rows in input.json.
For each write index/ref, independently read expected fields, observed fields,
source page/table, correct/incorrect/uncertain and reason to activity-checks.json.
Whole-row correct needs label/target/endpoint/value/unit/operator/conditions/source
all checked. Do not drop uncertain rows. A core-value-only match is not full accuracy.
Check each distinct core and high-risk structure (at least 6 where available) with
actual source-image and RDKit inspection. Keep structure and crop-identity results
separate in structure-checks.json. Without image inspection mark uncertain.
Audit SAR and synthesis separately in edge-checks.json with endpoint/type/direction
and source reason. No text Evidence alone is not a failure. Do not require all pairs
or make Methods-only intermediates global compounds merely to fill a graph.
Write audit.json and audit.md with exact sample records, C/E/U/N/P, coverage scope,
missing labels, unknown denominators, unresolved source conflicts and limitations.
Never call AI review human gold or estimate global accuracy from this sample.
Save partial deliverables before budget expiry. Do not repair/apply the candidate.
```

两阶段是新的运行要求；historical audit 若仅按提示词要求先读源、候选已同目录存在，应如实记录为 procedural separation，不能追称物理盲审。
