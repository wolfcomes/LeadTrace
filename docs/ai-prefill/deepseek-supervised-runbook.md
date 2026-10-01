# DeepSeek 主导的预填与修补运行指南

流程 `deepseek-led-v3-20260923`，入口见 [START_HERE](START_HERE.md)。日常科学工作交给 DeepSeek；Codex 在 evaluation 模式监督、校准指南和报告。已有授权范围内由受信操作者交付 Preview。该分工降低昂贵监督的重复劳动，不降低源审查标准。

## 职责、模式和实际能力

| 角色 | 负责 | 边界 |
|---|---|---|
| DeepSeek 生产者 | 源清点、代表结构、提取、自检、有限修补、结构化交接 | 单篇单写者；不读凭据、不 apply；自检不是独立审查 |
| 新 DeepSeek 审查者 | 冻结范围的独立源核验，报告逐项结论 | 不继承生产者推理，不修改候选；仍是 AI 复核 |
| 受信操作者/任务工具 | 任务身份、打包、限时执行、确定性检查、状态和交付 | 不替模型宣称完成科学检查；凭据不进入生产目录 |
| Codex（evaluation） | 检查源阅读者表现、差异、统计、返工与指南效果 | 不读原始论文/源裁图/含源内容日志；不做重复科学提取 |

`routine` 默认让生产者连续推进；`evaluation` 记录额外监督/固定样本。两者的可交付质量条件相同。风险可触发独立代表结构检查，例如高风险立体骨架、源冲突、已发生可扩散错误；不要把每个中间文件保存点都变成新会话。

CLI `task prefill` / `task selfcheck` 生成新任务包；`task run DIR --timeout-seconds 1800` 运行一次有界 `dsh --profile headless` 生产调用并保存状态；`task status DIR` 查看状态。每个 job 只运行一次，重试/续修建立新 job 并引用父产物。任务锁按 paper_key 防止本机同论文并发写候选，即使 source 不同也互斥。当前没有全自动独立审查调度、科学批准、持久后台队列或 Preview 应用服务；不能把生产调用正常退出当流程完成。

## 输入包与最小阅读

每次新任务复制真实当前指南、prompt、schema、模板和授权源，冻结文件 hash；历史包保持原样。包中有文件不代表模型必须全部读取，模型按以下清单读取，其余仅遇到对应风险时打开：

| 阶段/角色 | 必读 |
|---|---|
| 新预填生产 | 实际 task/input 与外部来源身份记录、candidate schema、extraction-guide、task prompt；生成后读 self-check guide/template |
| 自检/修补生产 | input、当前候选/源 inventory、结构化 handoff 与反馈、self-check guide、revision prompt；extraction-guide 中受影响科学章节 |
| 独立审查 | 实际源身份、冻结审查范围/候选 hash、audit protocol/prompt；受影响科学章节 |
| 操作者/Codex | START_HERE、本文、实际 HANDOFF/state、质量清单；Preview 操作时才读 Preview runbook |

`quality-pitfalls.md` 是按风险查阅的错误模式表，不是每个调用的额外必读。完整原候选和历史证据可作只读后备；默认给修补者紧凑 handoff、准确当前版本和差异，不要求重读全部旧报告。共享图像/解析产物可按源 hash 复用；不能把缓存存在当实际视觉检查。

源身份从外部 catalog/manifest 选定，记录 paper key、DOI/题名、SHA-256、bytes、pages；DeepSeek 核对实际 PDF。SI 单独列身份与可用性，不把正文 Experimental 称为 SI。input prepare/task prepare 不会自动证明源选对。操作者在派发前核对 catalog，可在 input.recipe 保存 expected_title/expected_doi/catalog provenance；提供独立 source-identity-check 文件时才要求模型读取它。记录真实模型/harness、指南文件 hash 和提示词；未知 usage/费用为 null。

## 运行前核实模型和推理配置

质量优先不等于在提示词里写“尽力”。操作者应核实实际 `dsh --version`、
`headless` profile、provider/model、thinking、reasoning effort、单请求输出上限、
上下文及图像处理限制。区分默认配置、配置覆盖和实际请求元数据；没有实际记录
时不能声称历史运行使用了最高档。`--dump-config` 可能含敏感配置，禁止原样
输出或放进生产包；仅保存脱敏白名单及配置文件 hash，不读取推理/源内容日志。

查阅当时官方能力说明和安装版本的适配器。读取化学结构图的生产者/审查者
必须使用支持图像的模型；更昂贵或名称含 Pro 不自动意味着适用于本任务。
质量优先时显式选择适配器和服务端共同支持的最高 reasoning effort，冻结
本轮独立 overlay，避免修改全局用户配置。提高输出上限不保证更好科学结论，
墙钟限时也不是推理档位。确认图像没有被当作纯文本或低清缩略图；对细节
使用可辨认的局部原图，而非只增大整页图像。

使用不含论文内容/凭据的请求元数据或合成图像探针核验配置生效，再启动
科学任务；模型自述不是证据。记录请求模型、thinking/effort、max tokens、
图像输入是否实际发送、HTTP 状态及失败/截断。不要保存 headers、消息文本、
原图字节或 reasoning。服务端内部算力和科学准确率不能由这些参数证明。

## 从零重跑与指南对照

先保留原始/修补候选、审查、当前 Preview 工作区快照及 hash，再建立新的
`prefill` 任务。新生产包只含源和通用新指南，不含旧候选、旧错误清单、
由旧答案导出的 inventory 或 Preview 数据；生产者从源自行建立分母。
重新提取不要求清空已有 Preview。已有工作区仍按版本化更新规则处理，
需要并排展示时使用独立空白实例，不通过删除/重置绕过 initial apply。

派发前冻结检查范围、遗漏检查、结构/locator/Activity/关系的逐项分母和
独立审查规则。复用已诊断论文是回归实验，不是新论文泛化验证；同时改变
指南和模型/effort/预算时，只能评价整套配置，不把差异归因于指南一项。
汇总前以实际逐项记录校验覆盖和分母；端点正确但条件、描述或证据错误的边
不能计为整条正确。源歧义、诚实未决、遗漏和错误正向断言分别报告。

## 新预填：一个生产循环

### 日常调用边界与停止条件

| 阶段 | 调用和责任 | 结束条件 |
|---|---|---|
| 基线生成 | 一次生产者 harness 调用，含源清点、提取、自检与最多两次内部修正 | 保存最终候选和实际检查证据；未完成/未解决如实标记 |
| 基线独立检查 | 一次新的只读 reviewer 调用，按冻结范围先形成源判断再对照候选 | 交付逐字段/依赖结论与未查范围；不修改候选 |
| 条件追加 | 有证据可修的问题：一次新修补调用＋一次新的增量复核调用 | 只修问题及受影响依赖；两次追加后仍未解则交 needs_revision/partial |

因此基线是两次 harness 调用，追加闭环后是四次；每次会话可包含多个模型请求/工具调用，不把它们称为两次 API 请求。独立源清点、仲裁或代表结构预审若另建会话，也分别计费/计数，不暗藏在“两轮”中。当前工具没有自动编排这些步骤，仍由操作者派发。

生产者先形成源清单，审查者在自己的调用内独立核验其覆盖及排除理由；不默认再加一个全篇清点会话。隔离强度与源先行的实际安排按 [审查协议](quality-audit-protocol.md#1-冻结身份范围和检查计划) 记录。抽样通过只支持已查范围，未查字段不能因此获得全篇通过。

将剩余项区分为可修提取/编码错误、尚未完成的检查、缺少来源/真实歧义、审查争议。前两类不包装成“原文无解”；后两类无新证据时不循环返工。审查争议先核对实际字段及审查依据。预算仅允许基线时保留问题交付，不把独立检查写成“已订正”；条件追加后停止，进一步工作需明确的新证据或新的限定任务。

### 生产步骤

1. **调查并保存。** 未读旧候选先清点全部可用源内完整身份、测量、SAR/合成关系；记录缺失 SI/未决。每个不同结构家族和高风险连接/立体变体都给代表结构、源定位和实际重绘比较，不只核实最终 lead。
2. **代表核实后扩展。** 生产者先解决共性核心错误再生成全系列；未决家族可保留缺口，继续独立部分。每个最终结构和自身 locator 集合仍须视觉核查。按表/系列保存，避免预算末尾一次性写文件。
3. **程序检查和源自检。** 按 [自检指南](deepseek-self-check-guide.md) 执行；先修低成本可发现问题，再做科学检查。默认一次系统检查、最多两轮修正。无新证据的缺失 SI/原文冲突不重复派发。
   最终检查必须重新读已落盘候选：共核/变体映射、精确裁图、反馈对应的字段差异及依赖结论；不得用计划、临时对象或“已修复”自述替代产物。
4. **交付。** 完整候选、inventory、测量/结构/路线核验、最终 hash 绑定 self-review、自检报告、变更/未决与 handoff。状态区分 partial、needs_revision、ready_for_independent_review，不由生产者填写批准或 application receipt。
5. **独立审查。** 新 reader 按冻结风险范围和固定样本核验，见 [审查协议](quality-audit-protocol.md)。共性错误扩大到整系列/列；局部问题精确反馈到下一修补 job，不默认重跑全文。

## 已有候选：自检/修补入口

先固定当前父候选、源 inventory、已审查证据、反馈及 workspace 基线。已应用草稿须由操作者导出现状/核查人工改动，不能以原始预填 candidate 代替当前工作区。传入 workspace ID/version 只是记录，CLI 不联网保证它仍然有效。

原生产会话可用于追踪和未来续接；当前 headless 无 resume，实际使用新会话读取结构化 handoff。session inspect 只读取身份与 usage 元数据，显式 `--dsh-home` 应对应实际子进程环境的 DSH_HOME，不能把 terminal session ID/PID 当模型对话 ID。原生产者无论是否续接都不能成为独立审查者。

先列变更及受影响依赖：改结构核心影响全部变体及结构/SAR理由；改 crop 检查共享该区域的所有身份；改边检查相关组的成员、角色、非参与说明；改标签检查所有引用。未改变且有适用审查记录的项目保留；不凭文件版本变化重做所有检查。

复用审查须人工核实源 hash、实体内容 hash、检查范围和依赖 hash 均适用，保留原记录 provenance；当前工具不自动验证继承。仅改描述不能让结构审查失效，改共享骨架也不能只查一个代表。当前七项 source-self-review 无增量豁免：无有效继承的未查范围保持 unresolved，不把局部修补包装成全篇通过。

输出完整新候选及精确差异，保留原 IDs/refs 和未受影响内容；新 candidate ID、真实 parent 与实际 feedback IDs。运行器对修补输出保存 `checks/candidate-diff.json`，按实体 ref 汇总变化（Activity 按 compound_ref 聚合，不是逐测量身份匹配）；模型/操作者仍须检查意外改动。重写全部候选不是重新提取全部内容的理由。

## 审查与记录效率

- 结构记录共享核心一次，每个变体记录自己的取代/连接/立体差异与结论；每个制备事件记录底物、产物、条件、源位置一次，关联其二元边。压缩重复文字，不减少逐项覆盖。
- 候选校验、标签 coverage、自检先运行；self-check 的图诊断现已报告分量、孤点、环、合成角色冲突和逐 Compound 两类未参与，仅给 review 提示，不自动拆组/加边/批准。图含义、非参与理由和测量穷尽仍需源核验。
- 科学 disagreement 回源核查 expected 与 observed；审查者也可能错，不能盲改正确候选。已否定边不能为连图恢复。
- 冻结源清单/审查样本与候选 hash，独立审查声明其实际范围。用任务包隔离/清单元数据证明阶段边界，不要求 Codex 读 reasoning logs；单靠提示词的顺序约束仅称 procedural separation。

## 有界运行、恢复和费用

运行器记录实际 process/session identity、开始结束 UTC、退出/超时和产物。只终止本任务拥有且身份核实的进程组。工具 wait 报错先查持久状态，不盲目重跑；活动 Codex 结束不等于后台仍有人监督。跨论文可先保持 2–3 并发；避免大量轮询或重复读长报告。

`task status` 返回持久 checkpoint 和 leader_identity_matches，不能推断整个进程组实时状态。遗留 running 用 `task recover DIR`：只接受 running 状态，取得原 paper 锁并核对 boot/PID/start ticks/session 无活进程后标 interrupted；不终止/重跑，后续建新 job。锁默认位于 `~/.local/state/leadtrace/ai-prefill/locks`，可用 `LEADTRACE_PREFILL_LOCK_ROOT` 统一操作者；不同锁根不互斥。这是同机协作锁，不是分布式协调或文件访问沙箱。

timeout 是墙钟限时，不是模型 token/金额硬限额。提示词预算、最多修订轮数和停止条件仍需检查，当前未实现自动依赖继承验证或 token 费用强制预算。记录 DeepSeek/Codex 各自调用数、输入/输出/缓存 token、超时/返工、工具费用和人工分钟；未知留 null，缓存 token 不自动与总输入相加。session inspect 能提取的 usage 以实际字段与来源为准，不估算不存在的账单。

评价改进须比较相同源范围、独立审查标准下的准确性/覆盖、交付后缺陷、返工、总成本和墙钟时间；文档缩短、模型更便宜或调用次数减少都不能单独证明效果。

评估指南时冻结相同模型/effort/预算/来源/审查口径，分别比较基线两次调用后和条件追加后的结果。统计身份与测量覆盖、分字段正确/错误/未决、漏检/误报、共性错误和实际返工成本；不混成一个总准确率。已用于改指南的论文只作回归样本，另用未参与修改的论文检查泛化。一次新旧结果差异不能排除随机波动；没有实际对照不声称正确率提高。

## Preview 与跨任务交付

生产者只交文件。受信操作者按 [Preview runbook](../../leadtrace/ops/runbooks/ai_prefill_preview.md) 核对 source/实例/候选 hash/授权/角色/workspace 版本。空白工作区才使用 initial apply；已有数据用版本化 Reviewer 更新，前后快照与 journal 保留人工编辑，409/403 时核查约束，不清空/回退版本绕过。旧 receipt 的 changed_since_apply 可是合法编辑，不能伪造新 receipt。

用户授权查看未完善结果时保持 draft/needs_revision，明确未决；可查看不等于科学通过。写入后核对实际数据、分页、边、生成结构和资源可读取，计数/HTTP 成功不是科学验证。Preview 科学记录/候选/资产不导入生产；合并源码不授权生产部署。

用 [HANDOFF](templates/run-handoff.md) 与 [run-state](templates/run-state.json) 保存实际完成范围、产物 hash、会话/进程、检查/审查/交付各自状态、禁止重跑事项与唯一下一动作。能力边界和受限网页 broker 方案统一见 [MAINTENANCE](MAINTENANCE.md)。
