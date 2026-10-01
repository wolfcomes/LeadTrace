# 独立源审查与增量复核协议

流程 `deepseek-led-v3-20260923`；CandidateEnvelope 与 source-self-review schema 仍为 v1。独立审查由新的 DeepSeek 上下文执行，不能继承生产者推理或把生产者自检换名。AI 复核不是人工金标准，审查者也可能错。科学细则统一见 [提取指南](extraction-guide.md)。

## 1. 冻结身份、范围和检查计划

任务源身份链为外部 catalog/manifest→实际源→input/candidate→目标工作区。记录 paper key、DOI/题名、源 hash/bytes/pages、审查人、范围/样本。hash 按类型比较：candidate_file_sha256 与 canonical_candidate_sha256、inventory_file_sha256 与 canonical_inventory_sha256 不能混比；类型不同不证明 stale，沿用程序标注的 hash kind。DeepSeek 读源，Codex 查元数据/产物。

| 层面 | 分母/判定 | 不可混同 |
|---|---|---|
| Compound 覆盖 | frozen source inventory 中 required 身份；另报 all-inventory | 不证明结构正确或源清单穷尽 |
| 测量覆盖 | 源 measurement tuple 清点与候选匹配 | Activity 条数不是独立实验/全篇测量分母 |
| 科学准确性 | 实际逐项核查范围的 C/E/U | schema、自检声明、图加载不是源科学核验 |
| 本轮修补 | 改动＋受影响依赖的审查结果 | 局部通过不刷新所有旧数据的科学结论 |

首次预填的生产者先从源建立 inventory。日常 reviewer 在同一次新调用内先核验源的身份范围/角色/排除与高风险核心，再与候选和生产者清单比较；生产者清单不能当独立金标准。若没有可信清单，先保存自己的源清点再比较，不能以候选反推分母；来不及完成就交 partial。清单有错时另存修订与理由，不改旧清单使其迎合候选。已有有效源清单的修补不要求每次重新做全篇调查；检查 exclusions/未决/新增来源范围，缺陷或范围改变才扩展。评测需独立 source-only 调查/强隔离时可另建任务，但这是额外调用，须计数，不是日常两次调用内自动存在的步骤。

用分阶段目录/实际文件 manifest、源清单 hash 和候选提供时点记录隔离。目录隔离不是操作系统沙箱；未实现访问控制时明确限制。仅提示词要求“先读源”只能称 procedural separation，不能宣称物理盲审。Codex 不读取推理日志来证明顺序，也不从会话 ID 推断独立性。

## 2. 覆盖清单

CompoundInventory v1 使用 [已有 schema](schemas/compound-inventory-v1.json)，只写实际 observed labels、aliases、required、role、source_locator、exclusion_reason；不向 schema 加自定义分组字段。完整编号/标签结构包括起始原料、中间体、Methods-only、共享核心＋R 基、参考物/控制。未决完整身份仍 required，不能用猜结构或 required=false 消除缺口。无图不排除真实对照；纯背景引用、泛式、普通试剂按源角色/位置说明不适用，不把所有药名自动当对照。

运行 `candidate coverage candidate.json --inventory compound-inventory.json`。required 缺失/歧义退出 4；omissions 不让它通过。并列 required 与 all_inventory_coverage、每项 missing/ambiguous/excluded/extra；不以候选自身定义分母，不按连续编号补造清单。标签匹配不证明科学身份，AI 清单不等于人工完整金标准。

观察按 compound＋assay/endpoint＋条件＋源位置匹配，并核对 destination：Activity、计算性质、证据/结构上下文、重复、冲突、图未决。分别报告真正漏提与已解释去向，不能将全部 missing slots 当漏 Activity；家族计数从明细重算。缺失项不加入已有行准确率分母。SAR/合成分别清点合理关系，不要求所有配对。

## 3. 首次候选审查与修补复核

首次候选预固定 Activity 基线样本：N≥20 时取索引 `floor(i*(N-1)/19), i=0..19`，不足 20 全取；另补不同表/靶点/单位/比较符、lead/control 和高风险项，去重记录原因。结构覆盖每个核心及高风险连接/环/区域/立体/盐型，至少 6 个可用样本；不足全取。样本外扩查另列，不能看完结果只报告好项。

修补审查先冻结所有新/变更实体和依赖范围，逐项核查本轮科学改动。无科学变化的纯格式/组名调整检查其一致性，不重做未受影响分子的结构核验。共性错误扩查整个系列/表列，改变共享源 crop 检查其所有依赖；无法完成时明确未查数量，不能称变更已全部核实。

有效继承记录需包含源 hash、实体 ref/内容 hash、检查类型/范围、共享核心/图例/反应等依赖 hash、原结论及 provenance。内容/源/依赖变化使对应结论失效；仅候选文件变化不自动让所有科学证据失效。工具尚不自动验证继承，操作者须核对；新最终 self-review 仍绑定新文件 hash，不能只替换旧 hash 后宣称重新核验。

## 4. 逐项证据与语义

环系核验须按 [源原子连接对照](extraction-guide.md#ring-system-verification-record) 留下独立 expected 与候选 observed：共享原子/键、桥端点路径、杂原子、取代锚点及适用立体。没有完成这些检查不能将该核心的连接判为 correct；不以生产者“共核已核实”代替源判断。Activity 的截图和关联同时按 [区域身份规则](extraction-guide.md#activity-evidence-region-identity) 检查；精确框的内容、表头/脚注支持与测量归属须分别有结论。此规则加强科学审查记录，不代表 CLI 已实现语义自动验证。

- Activity 每项保存索引/ref、源位置、独立读出的 expected、observed、结论和理由。整行 correct 须核对 compound/target/assay/endpoint/value/unit/operator/conditions（适用 SD/SEM/n 等）/来源；只查值则 uncertain 或单报 field-level。
- 结构与 crop 分别记录。先从源独立形成共核的连接/稠合/anchor 判断，再检查候选文件实际编码的图及其重绘；不能沿用生产者“已通过”的核心。将该源核心映射到各实际变体，结构变化、保护基与立体仍逐项核查。发现共性错误扩查整族，未查变体留明确状态；不以可解析、分子式、相同 SMILES 片段或固定环大小禁令判定身份。实际渲染唯一最终 bbox 一次，映射其支持的完整身份。未看图则 uncertain，不能以代表图、近似 crop 或 locator 存在声称全量核实。
- SAR/合成分开查类型/端点/方向/依据；同 pair 可同时成立，但不能只复制反应理由充当 SAR。无 quote 不自动错，有 quote 不免检。制备事件一次记底物/产物/条件/定位并关联边，制备数不等于边数。
- Lineage 逐组范围、分量/孤点、角色冲突和解释，逐 Compound 两类参与及原因，论文优选理由/未知，按 [分组规则](extraction-guide.md#lineage-grouping-roles-and-participation) 核查。不能为连通补边或恢复已否决关系。
- 发现矛盾先回源复核 expected，保存审查修订轨迹；原文矛盾与提取错误分开。源未提供 SI 不等于正文 Methods 信息也不存在。

核对 review_hint 与实际源依据和疑点是否一致：完整结构可由共享骨架、R 基或反应关系合理重构，不要求每个分子都单独画出；仅有编号范围而无可推导图仍不收录。提示不能使已知错误或未核项判为 correct；既核查无依据的猜测，也指出有依据候选被过度遗漏。解决疑点可建议清除提示，未决提示须保留；独立审查本身不修改候选。

按字段保留结论：结构的连接/区域/立体/化学形式与定位；Activity 的值/单位/算符、条件/统计、来源及分子身份；Edge 的类型/方向/步骤/解释及端点身份。整项有已证实错误就不能 correct，有未核字段也不能声称全字段通过。已知端点结构错必须反映在关联边/Activity 的身份判定中，不能用“标签配对正确”消除该依赖错误。

对“缺少 raw token/条件/出处”等指控，先读取最终候选的实际字段及 context，明确缺失位置或保留的内容，再判断科学表达是否正确；不要把字段存在性与语义正确性混为一谈。源有 SD/SEM/n 歧义时忠实保留原表述并标记解释未决，不擅改统计定义。数值错误、统计/条件错误、出处冲突分别计数。

修补复核按 [最终产物闭环](deepseek-self-check-guide.md#最终产物与问题闭环) 检查反馈→实际字段差异→源依据→依赖结果。修补声明不是差异证据；声明与产物不符即报告未闭合。先检查真实产物，再审计生产者说明，不照抄其“已修复”列表。

Lineage 修补复核须先保存本次范围内独立的源制备/比较清单，再对照最终边、删除边与遗漏；之后才审计生产者账本与 checked 声明。已有可信清单可复用，但账本齐全不能自行证明科学成立。同 pair 存在合成关系不否定有独立依据的 SAR；范围未映射的个体结构也不会因为写了“推断/未决”而变成已确认。

记录原子级结构、图端点/方向、完整条件/步骤、描述和裁图的具体检查范围。若边的端点正确但同一审查在依赖记录中发现漏步骤，汇总必须保留该字段错误，不能报整边全部正确。共享裁图核查要显式关联全部依赖 locator refs；只写代表图不能填空的 unreviewed 清单或宣称完整范围。先完成约定范围，再扩查，无法完成则列明未查 refs。

## 5. 统计、停止与交付

逐项 `correct / incorrect / uncertain`，C+E+U=N，同时显示检查数/总体数 N/P；主指标 confirmed_fraction=C/N，resolved_accuracy=C/(C+E) 可另列但说明排除 U。非全量时 whole_population_accuracy=null；未知源总体为 null；不将偏向高风险的样本外推总体准确率。

汇总前交叉核对逐项记录、依赖问题、自检审计与摘要；理由写“仍错/未核”而 verdict=correct 时先纠正矛盾再计数。逐 ref 有一条记录不等于其所有字段都已核实；同时报告字段范围/未查项，不混合结构、数值、出处等分母。保留原报告，纠正记录另存，不能以摘要覆盖细项错误。原文箭头、扩展制备事件、边、检查记录和唯一实体分别计数。

立即保存已查项，未查/受阻明确状态；预算到达交 partial。没有新证据的未决不重复调用。输出逐项审查文件、简短结论、精确 hash/范围、遗漏/冲突/限制和下一步。审查者不改 candidate、不 apply、不填写生产者自检或审批回执。独立审查正常结束不等于所有项正确；日常和 evaluation 均遵守以上标准。

若候选含可选 Abstract/PDB 元数据，独立审查需核对原文摘要与摘要来源，检查每个结构编号确被提及、页码有效、用途及 Compound 配对未被猜测。发现摘要被改写为模型总结、配体代码被当 PDB ID、引用结构被写作本文结构时报告具体字段与证据。字段缺失按未覆盖报告，不自行认定“未报告”。

### Article Compound highlights

For study_start / paper_selected annotations, follow extraction-guide.md's
article-level definitions. Before candidate comparison, create an independent
role matrix from the Abstract, Introduction/Design, Results/SAR and
Discussion/Conclusion. For every row check the exact author statement, scope,
all compounds named by that statement, selection rationale, linked Compound
structure and Evidence identity together. Neither the lowest/first label, first
table or scheme entry, terminal degree, last synthetic product, in-vivo/PK
appearance, nor strongest single-assay activity establishes a paper choice.

Multiple study starts and multiple paper-selected compounds are valid. A single
row covering only one member of an explicitly named set is
`role_incomplete_or_ambiguous`; do not confirm it as the sole endpoint. If the
compound/role is supported but its linked table/scheme/PK Evidence only proves
existence or an observation, classify it as `evidence_linkage_error` and require
an Evidence replacement. If the compound conflicts with the source, classify it
as `role_identity_error`. A source that does not explicitly select a compound is
not permission to promote the best numeric assay result.

Address each result under compound_scope with PDF locations and a specific
unknown/absent outcome; do not treat a missing list as proof of absence. AI emits
no reviewer confirmation. When a structure or source attribution changes,
recheck dependent highlights as well as Activities and Edges. Independent review
must verify these assertions afresh; a passing schema check is not scientific
approval.
