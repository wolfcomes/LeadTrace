# 模型自检与修补入口

流程 `model-neutral-v4-20261008`。适用于首次提取后的生产者自检，也适用于 `task selfcheck` 创建的已有候选修补任务。两者均由生产者完成，不是独立审查；不自行批准或写入 Preview。科学细则以 [提取指南](extraction-guide.md) 为准。

## 先固定现状和检查范围

1. 核对当前候选文件 SHA-256、源身份、inventory、实际 parent/feedback、结构化 handoff。已有 Preview 以操作者提供的当前导出和工作区版本为基线，不能覆盖后来的人类修改。
2. 首次自检覆盖本次全部提取；修补先列 changed refs、疑点和影响依赖，再核查相关源。源清单可复用但不能用候选自身反推分母；发现缺失范围就扩展清单，保留原版与理由。
3. 原生产会话只用于追踪；当前 dsh headless 无 resume，使用新 job＋handoff 继续。独立审查另建 fresh reader。未改变的有效源审查可继承，但须记录源/内容/依赖 hash 与实际范围；此继承目前不由工具自动证明。
4. 默认一次系统自检、最多两轮修正。已知原文冲突、缺失 SI/结构未决在没有新证据时保留，不反复调用凑通过。保存可用产物和明确未决。

## 先程序检查，再源核查

从所选工作树运行；生产者只访问本任务文件和已安装模块，不访问凭据/数据库。绝对路径由任务填好：

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate self-check /absolute/job/candidate.json --inventory /absolute/job/compound-inventory.json --output /absolute/job/self-check-preflight.json
```

首次没有 `--self-review`，`SELF_REVIEW_MISSING` 和退出 4 是预期。检查完整报告，先修确定性问题，再按下表实际回查源；不靠把状态改为 checked 消除错误。

| 固定 check_id | 必须记录的源检查范围 |
|---|---|
| `compound_scope` | 源清单、所有完整编号/标签身份、required 与全 inventory 缺失/歧义/排除；未决完整身份保留 required；泛式/开放片段不是完整 Compound，说明其不适用原因 |
| `measurement_coverage` | 表/图/正文测量 tuple 与 candidate 索引；numeric/censored/ND/qualitative/graph-unresolved 分开，未知分母保持未知；缺失测量与已录入行准确性分开 |
| `activity_semantics` | compound/target/assay/endpoint/value/operator/unit/raw token/SD或SEM/n/条件；剂量作为条件，ED50/MTD 等真实终点例外；S.I. 无量纲；重复报告不冒充独立实验 |
| `structure_identity` | 每个最终结构源图与重绘的核心/连接/环/取代/保护基/区域/立体/化学形式；新增参考物单独核对，外部推定结构不称源图已确认 |
| `source_crops` | 每个 Compound 自身的完整骨架＋编号行＋R 基/连接基定义；检查实际最终 crop、表格首末行、OH/电荷/必要脚注；重绘不是原图 |
| `sar_reasoning` | 实际端点、结构变化、方向、比较限制、lineage 组织/参与与论文优选依据；无 text evidence 的合理推断允许，不按编号造关系 |
| `synthesis_paths` | Scheme＋Methods 的真实前体、直接/多步、条件、共同反应物、路线/edge 一致性和 lineage 组织/角色/参与；制备次数与二元边数分开 |

已收录 Compound/Activity/LineageEdge 有具体不确定或冲突时，按提取指南填写可选 review_hint（依据＋疑点）；缺少可找到或合理推导的完整结构仍不写入 Compound。提示不豁免已知错误，也不自动代表 correct；修正后有依据才清除。

详细审计仍用现有 sidecar/notes 中的短记录，不新增其他 Candidate/schema 字段：

| 记录 | 最小字段与判定 |
|---|---|
| 身份例外 | label、源角色/位置、eligible、structure_resolved、去向；eligible 未解仍 required，暂缺 candidate，不因结构必填猜 SMILES |
| 结构 | core_id、从源确定的连接/稠合/anchor/位置/立体、源、结论；各 variant 的最终结构内容 hash、实际分子图/重绘、映射/差异/分字段结论，代表通过不等于全系列通过 |
| 原图 | 唯一 source/page/最终 bbox、实际检查产物、完整可识别 labels、依赖 locators；共享裁图只查一次，不以整页或近似裁图替代 |
| 观察去向 | 源位置、family、kind、expected/matched/unresolved、destination；Activity、计算性质、结构/证据上下文、重复、冲突、图未决分开 |
| 图异常 | diagnostic ref、原因、有依据的修正或未决；SAR/合成同 pair 须各自依据，编号范围不证明前体逐项映射 |
| 七项覆盖 | check_id、checked refs/源单元、unresolved refs、unreviewed refs、证据记录/有效继承；状态由该范围决定 |

状态为 `checked / unresolved / not_checked / not_applicable`。要求范围中仍有未解或未查项时不得 checked；写在 details/handoff 的限制不能豁免，未审范围无有效继承即 unresolved。compound_scope、measurement_coverage、structure_identity 不可豁免；已有相应数据不能豁免其检查。checked 必须有 source_locations，checked_edge_refs 只列真实边。图语义、逐类型非参与和优选仍遵循 [分组规则](extraction-guide.md#lineage-grouping-roles-and-participation)，不得恢复已否决边。

## Lineage 记录的闭合检查

保存 `lineage-evidence.json`（或有等价索引的已有记录），绑定最终候选文件与源 hash：

- 源制备/比较单元有稳定 ID、具体位置、标签映射和未决；每条最终 Edge 都关联核验记录，另列源中已见但未表达的关系。
- 每个 Lineage 有范围、分量/孤点、组内角色和跨组衔接处置；每个 Compound 分别有 SAR 与 synthesis 的参与状态、原因及证据或明确未查。
- 优选结论独立记录范围/理由/来源；共享核心、裁图或事件可复用，但列出所有依赖 refs 及逐项结论。
- 检查所有最终 refs 是否有记录、有无重复/失效映射，并核对 `checked` 与实际已查/未查/未决范围。`verified` 字符串、记录齐全、零孤点都不是科学证明；未决端点依赖不能被概括为整条关系全字段已确认。

当前 CLI **不强制校验此 sidecar 契约或记录真实性**，上述核对由生产者和操作者执行，新 reader 独立回源验证。图关系、结构、裁图、测量和自检声明分别报告；证据框的页码/类型/引文须相符，不能用定位到图的 bbox 代替另一页正文引文的定位。

## 最终绑定与交付

### 最终产物与问题闭环

在现有 notes/sidecar 中记录以下检查，不增加 Candidate 或 self-review schema 字段。产物和记录必须对应**最后一次落盘版本**：

- 重新读取保存后的 candidate，按实际结构字段重绘/检查；源确认的共核与所有变体逐一映射。连接、稠合、取代位置、保护基、立体分别记录。按 [环系检查记录](extraction-guide.md#ring-system-verification-record) 保存源原子连接与最终结构的对照依据，不能只写“RDKit 通过／环数正确”。可解析、分子式或系列内一致均不能证明源身份；代表修好后仍须列出整个受影响家族的最终结果。
- 从最终 locator 集合生成唯一 source/page/bbox 清单，检查这些精确裁图并关联全部依赖 refs。裁图改动后旧图结论失效；脚本运行成功、临时框正确或看到整页不能证明最终框完整。
- Activity 证据按 [区域身份规则](extraction-guide.md#activity-evidence-region-identity) 检查编号行、表头/单位/脚注及实际关联；分别记录关联错、定位错、裁图缺上下文和数值错，不把看见同一个数值当作来源通过。
- 每个反馈 ID 记录对象/字段、父版本实际值、最终实际值、源检查依据和处置：已修并核验、反馈不成立（附依据）、或仍未解。没有相应差异及核验不得写“已修”；若对象删除/移入未决，保留身份/已知观察并说明这不是恢复正确覆盖。
- 核对预期受影响 refs 与实际差异，逐项解释未改/额外改动。Activity 不能只按行号或 compound_ref 聚合判断，需结合 compound＋assay/target/endpoint＋条件＋来源定位，并保留父/子索引；歧义匹配留未决，重复来源不合并成一次实验。
- 错误结构影响关联 Activity 的分子身份及 Edge 的端点/结构变化结论；数值或标签方向可单独正确，整行/整边不能据此通过。更新这些依赖的结论、组内角色和覆盖，不凭改了共核就继承旧结论。
- 从明细重算“已修/仍错/未查/未决”和 checked 范围，再绑定最终文件 hash。将提取失败、未完成核查、缺源/真实歧义及审查争议分别说明；避免把执行失败写成源缺失。

以上是执行约定，当前 CLI 不自动证明共核映射、逐反馈字段闭环或审查真实性。未完成时如实保留 needs_revision/partial，不以补齐记录字符串代替检查。

保留 `candidate-before-self-check.json`；正式父候选不覆盖，新版本保留真实 parent/evaluation 链。保存完整新 candidate、冻结 inventory、上述适用记录、quality-record、自检差异与 unresolved；共享核心/制备事件一次记录，每个变体/边仍须映射和结论。

对最后一次改动后的 candidate **文件字节**计算 SHA-256，按 [现有模板](templates/self-review.json) 填 self-review，然后生成程序报告：

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate self-check /absolute/job/candidate.json --inventory /absolute/job/compound-inventory.json --self-review /absolute/job/self-review.json --output /absolute/job/self-check.json
```

退出 0 是 `ready_for_independent_review`，4 是 `needs_revision`，2 是输入不合法。0 只说明已实现规则和源自检声明通过，不证明声明真实，不代替新会话中的独立审查。`supervisor_preview_gate` 保持 not_reviewed，交付字段由受信操作者填写。

程序已有 schema/引用/可解析性、required 缺失/歧义、特定 dose/ratio/重复 Activity、lineage 分类、七项完整性/豁免/hash/edge refs 检查；新增图诊断报告分量、孤点、环、合成角色冲突和逐类型非参与，均为 review 提示，不自动改图。尚未自动证明图语义、非参与原因、优选依据、测量穷尽、立体正确、crop 内容、合成条件、审查统计或继承有效性。不要把渲染脚本运行、文件存在或 CLI 通过当源核验完成。

文章元数据自检：若输出 Abstract，核对它是原文摘要并记录来源；逐一核对 PDB ID 的格式、实际提及页码、本文/引用/未知用途和可选 Compound 配对。空数组不证明作者未报告。不要混入三字符配体代码。具体字段以提取指南和当前 schema 为准。

### Article Compound highlights

For study_start / paper_selected annotations, follow extraction-guide.md's
article-level definitions. Build a role matrix before accepting the draft:
author wording/location, study or series scope, every named compound, and
whether the source is an explicit role statement or only supporting observation.
Reject numbering heuristics (lowest/first label, first table/scheme row, last
product), graph-degree heuristics, and single-assay/PK/in-vivo heuristics.

Allow multiple `study_start` compounds when the paper distinguishes a literature
hit from an internal lead, and allow multiple `paper_selected` compounds when
the authors advance a set or parallel endpoints. A single row covering only part
of a named set is unresolved, not confirmed. If the role is supported but the
linked Evidence only proves existence, synthesis, one assay, PK, or in-vivo
appearance, record `evidence_linkage_error` and replace the Evidence; if the
compound itself conflicts with the source, record `role_identity_error`.

Address these outcomes under compound_scope with locations and specific
unknown/absent results; an empty or missing list is not proof of absence. AI
emits no reviewer confirmation. When a structure or source attribution changes,
recheck dependent highlights as well as Activities and Edges. Independent review
must verify these assertions afresh; a passing schema check is not scientific
approval.

Admin 草稿交付与科学自检状态分开：退出 4 / needs_revision 不再单独阻止有效候选入库，问题报告和未决身份必须保留。启动预填授权保存草稿，不授权科学批准；格式、源/候选身份、引用安全和目标工作区版本检查仍必须通过。报告缺项也要明确展示，不能以先入库为由跳过自检。
