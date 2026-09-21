# DeepSeek 受监督预填运行指南

适用范围：由 Codex 组织多个 DeepSeek harness，生成供人工复核的 CandidateEnvelope.v1，并通过现有 AI Prefill 模块写入隔离 Preview。工作流版本和新任务入口以 [START_HERE.md](START_HERE.md) 为准。

本指南与 [质量规则](quality-pitfalls.md)、[交付自检指南](deepseek-self-check-guide.md) 共同组成当前指导。科学准确率和成本改善必须由独立审查及实际费用记录支持，不能从进程正常退出或技术验证通过推导。

## 推荐分工与并发

| 方式 | 收益 | 主要代价 | 使用建议 |
| --- | --- | --- | --- |
| 单 harness 全流程、结束后检查 | 操作简单 | 共用错误骨架可能污染整篇；发现问题晚 | 小型探索可用 |
| 多 harness 各负责一篇，Codex 分阶段验收 | 并行提取，检查方法统一，集中处理疑点 | 需要监督容量与可靠状态记录 | 推荐，先保持 2–3 篇并发 |
| 每篇双模型独立提取再比较 | 可发现部分不一致 | 推理费用更高；同源偏差仍可能一致 | 仅用于高风险骨架、立体化学和关键数据复核 |

单篇是默认写入边界：同一篇同一阶段只有一个候选写者，不让多个 harness 修改同一个 candidate 文件。Codex 可以在一个 harness 提取时检查另一个已交付的候选。监督积压达到当前并发数时，先暂停派发新论文，消化检查与反馈。

当前活动任务内，Codex 可以启动并监控多个进程、读取产物、发送下一轮提示词并通过已有 API 应用结果。用户要求监督者不读原文时，Codex 只检查文件身份、候选、指标和审查产物；源文核验交给新的 DeepSeek 审查进程，报告必须称为独立进程的 AI 复核，不能称为 Codex 原文核验或人工金标准。活动任务结束后，不能假设 Codex 会持续后台值守。跨会话自动恢复、定时唤醒与无人值守调度需要额外的持久协调机制；本轮文档没有实现这些功能。

## 输入与阶段验收要求

执行 [覆盖与准确性审查协议](quality-audit-protocol.md)；新增 [独立源文审查提示词](prompts/deepseek-audit.md)。派发前核对外部 manifest 身份，不再仅核对 input/candidate。调查必须产出合法 inventory 与代表结构阶段验收，避免只在 prompt 写“survey”却一口气生成全部候选。实际包必须含当前指南与文件 hashes；历史实验保留原指南版本。

对共享结构/表格发现的错误按整个系列/列扩大复查：本次 013 重复环编号冲突，010 区域位置误读，005 新表漏填。先修正生成策略/行列映射并验收代表，再批量展开。不要用反复提醒同一句规则代替阶段产物。

## 投入前准备

每篇建立独立目录，每轮使用新子目录。任务包中提供以下文件：

- `input.json`：真实 source identity、授权 PDF locator、guide_version、父候选和反馈 IDs。
- 原文 PDF；可选 `pages.txt`，只作为搜索辅助。SI 若另有文件，记录其独立身份；不要把 SI 页码伪装成主 PDF 页码。当前候选的 source 和 locator 以所选源为准，无法表示的外部来源留待明确的扩展流程。
- `candidate-schema.json`、`candidate-example.json`、`extraction-guide.md`、本指南和 `deepseek-quality-checklist.md`。
- 从 [任务提示词模板](prompts/deepseek-task.md) 填好的本轮 `prompt.txt`，以及 [质量记录模板](templates/deepseek-quality-record.json)。

复制模板不等于接入完成。监督者必须确认工作目录里确实存在文件，提示词引用的路径正确，`input.guide_version` 与实际指南版本一致，并保存输入、指南、prompt 和 schema 的文件 SHA-256。不通过修改全局默认 guide_version 来改写历史实验。

运行前实际计算 PDF SHA-256、字节数和页数，与 input 对照。`input prepare` 接收调用者传入的身份；不能把成功生成 JSON 当作已验证 PDF。纯离线 CLI `candidate validate` 也不能证明声明的 source hash 对应真实文件。复制包和 Preview 选中的 PDF 要分别核验。

任务目录写权限、只读 PDF、无数据库/Preview 凭据是推荐执行边界。提示词本身不是操作系统沙箱。当前 `dsh --profile headless` 的启动方式不应被描述为已实现强制目录隔离；需要强隔离时用受限账户或容器实际限制文件、网络与凭据访问。

## 阶段与放行条件

下列状态是监督者的运行约定，不是现有 CLI 已提供的队列状态。状态和每次转移原因写入单独的运行记录。

| 阶段 | DeepSeek 输出 | Codex 检查与下一步 |
| --- | --- | --- |
| 准备 | 已读取任务包、身份一致 | 检查源文件与输入版本，才能启动 |
| 论文调查与骨架试做 | `survey.md`、代表结构及原图、表格/化合物清单 | 检查每个不同核心、环大小、连接点和高风险变体；发现共性错误先修核心 |
| 全量提取 | 新 `candidate.json`、`quality-record.json`、`review-notes.md`、脚本和重绘 | 技术验证，然后做独立科学检查；禁止直接由 harness apply |
| 需要修订 | 保留父版本，读取精确反馈 | 下一轮只针对反馈与发现的同类缺陷修改；记录全部实际变化 |
| 可进入预览 | 精确候选 hash、检查结果、未解决项 | 由监督者应用，检查目标工作区版本和应用回执 |
| 预览验收 | 页面、图片、分页、草稿 Edge 与数据核对 | 验收通过才交付给人工复核；仍不是科学批准 |
| 暂停待处理 | 超预算、反复无进展、源文件缺失或不可解结构 | 保存产物及原因，停止自动循环；针对缺口升级处理 |

每阶段可以使用独立的 headless 调用，依赖磁盘文件恢复，不依赖模型记住上一轮。调查阶段的代表结构不是完整 CandidateEnvelope，不交给 candidate import。调查清单可以存在不确定项，但明显错误的共享核心不能带入全量生成。

### 调查阶段：优先阻断可扩散错误

先列出所有正文表格、结构图、药理/ADME/PK 章节和缺失 SI。按原文标签列出目标化合物，标记共享骨架、独立画图、控制药、未确定身份。

每个不同核心至少提供一个代表结构；此外必须覆盖环扩张/收缩、连接基改变、区域异构、糖基或其他立体化学变体。提供原文区域、带标签重绘、结构表示、环大小/核心说明。源图审查者核对实际图像、提供逐项记录后，监督者才让同类结构批量展开；监督者遵守用户对原文访问的限制。

PfPKG 004 的漏填修复进一步要求：先建立独立标签清单，再运行 `candidate coverage candidate.json --inventory compound-inventory.json`。不能用已有候选定义提取范围，也不能只收录已经有 Edge 的 Compound。真实例子见 [39 个主表化合物清单](examples/compound-inventory-pfpkg-004.json)。该命令已实现，缺少必填标签时退出 4；记录 omissions 不会使覆盖通过。它是监督者写入前必须执行的检查，尚未自动强制到 Preview API。

这一阶段旨在提前发现问题，不能代替全量结构逐一对照。RDKit 环集合在稠环体系中未必等于直觉的“环数”，环签名仅作异常筛查，不能硬编码“所有大环都是错误”。

### 全量阶段：要求可检查的中间产物

按表格或系列持续保存进度，结束时提交完整候选。质量记录必须列出每个源表的预期行标签、已提取标签、遗漏及原因；结构定位覆盖按不同 compound 统计，不能用 locator 总数替代。

DeepSeek 在扩展到全量前应采用经检查的片段组装策略。不能将含未闭合环编号的任意 SMILES 子串直接嵌套拼接。每个最终结构仍需 sanitize、重绘、对照原文，检查保护基、取代位置、连接点、立体化学和电荷。

所有新增 Activity 按原始 compound/assay/target/endpoint/context 记录；剂量留在条件中，重复表格上下文不伪装成独立重复实验。原文数值的检查参照必须独立读取 PDF，不能从 candidate 自动回填“参考答案”。

### 检查与反馈阶段

使用 [质量检查清单](deepseek-quality-checklist.md)。可解析不等于身份正确，图片加载不等于裁剪完整，退出码 0 不等于科学检查通过。

检查分为提取者自检、独立审查进程的源文复核、监督者的确定性与交付核验。新的 DeepSeek 会话与提取者隔离上下文，仍可能共享模型偏差；它不是独立人工金标准。Codex 未读原文时不得填写自己完成了源图/数值核验。发现一个共性结构错误或表格错列，要扩大检查到全部受影响系列/列，不能只修举例的一行。

模板中的 supervisor_preview_gate 由监督者独立填写，DeepSeek 输出时保留 not_reviewed；修订后也必须重置。监督者不把模型写出的 pass 或放行字段当作授权依据，应另存自己生成的、绑定精确候选 hash 的检查记录。

反馈使用 [反馈模板](prompts/deepseek-revision.md)，必须指明候选版本与文件 hash、实体/表格/页面、已观察到的错误、受影响范围、预期修复证据和不应变动的部分。反馈文件是运行侧记录，不自动等于模块的正式 Evaluation。已应用工作区的正式反馈需要 `evaluation record` 绑定真实应用和快照；不得伪造 application/snapshot 身份来使离线反馈看似通过正式契约。

每篇默认允许全量后的两次修订尝试，这是起始运行策略，不是已测出的最佳参数。同一缺陷两轮无改善则停止自动重试，由授权的源文审查者重查源图、改用局部专项检查，或保留明确遗漏。预算不足时保存部分结果，不能用补猜满足数量目标。

### Preview 应用与交付

DeepSeek 只交文件。监督者独立验证源身份、候选 hash、报告及工作区，再通过 Preview 专用 API 应用。保持稳定幂等键：同一请求恢复使用原键；不同内容不能复用旧键冒充同一次应用。请求超时先查询已有应用和工作区，不能盲目重发新键。

科学检查放行应绑定精确 candidate 文件 SHA-256；模块另有 canonical candidate/payload hash，二者用途不同，记录字段要区分。候选任何改变都会使旧的科学放行失效。

现有 Preview apply 只接收 version=1、空白、无 reviewer/admin 编辑历史的 editing workspace；`expected_workspace_version` 是并发保护，不是 replacement 开关。已有数据的工作区不能直接重新 apply。仅 label 等局部修正时，核对候选差异、保留前快照/原 receipt，使用指派 reviewer 的现有字段 PATCH API，逐请求版本保护并保存每次响应。Admin 管理权限不等于 draft 编辑权限。请求被 403/409 拒绝时先检查角色/业务约束，不清空科学实体、不回退版本、不伪造新 apply receipt；旧 receipt 的 `changed_since_apply` 可是合法编辑的结果。完整候选替换需独立规划与授权，不由此指南假装已有能力。工作区版本发生变化时先检查是否已有人工编辑，不覆盖或重置。三篇试验的 `apply_reviewed.py` 是含具体试验身份的脚本，不是通用调度器；复制前必须移除旧目标、核验新身份和版本。

验收包括应用回执 committed、活动字段与候选一致、图片实际解码、逐化合物来源覆盖、页面可读性、分页/筛选、草稿 Edge 和原有工作区未被意外修改。没有文字或支持 Evidence 的 Edge 可以保留，但应有具体 AI 推断理由；不要为通过检查造 Evidence。数值 Activity 仍应追溯到对应原文表格/文字；不要把 Edge 的允许规则推广成无需记录测量来源。

## 现有工具与待补能力

| 能力 | 当前状态 | 使用边界 |
| --- | --- | --- |
| `doctor`、`contract export`、`input prepare` | 已实现 | doctor 是离线可用性说明；输入身份需独立核验 |
| `candidate validate/import/compare` | 已实现 | 格式、引用、解析和差异；不证明分子身份或科学覆盖 |
| Preview candidates / validations / applications API | 已实现 | Preview 专用，登录及 CSRF，校验实例、源与工作区身份 |
| `evaluation record`、`candidate export-workspace` | 已实现 | 绑定实际 Preview 快照和版本；见现有 runbook |
| 并发运行、反馈修订、源图审查、页面验收 | 三篇试验中已实际执行 | 当前依靠任务内监督和试验专用脚本 |
| 持久队列、独占任务租约、统一重试与超时、重启恢复 | 尚未形成通用服务 | 后续调度器应补齐，不由文档假装实现 |
| 骨架错误、裁剪语义完整性、全量科学正确性自动判定 | 没有通用可靠判定器 | 确定性检查辅助，仍需源图对照与疑点升级 |
| 完整 token/费用与人工时间统计、质量趋势面板 | 本次未完整采集 | 下一批按统一口径记录，缺失值写 null |

可在仓库根目录运行以下已存在的离线命令（命令参数中的路径必须替换为实际任务文件）：

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill doctor
.venv/bin/python -m leadtrace.ops.ai_prefill candidate validate /absolute/job/round-1/candidate.json
.venv/bin/python -m leadtrace.ops.ai_prefill candidate compare /absolute/job/round-1/candidate.json /absolute/job/round-2/candidate.json
.venv/bin/python -m leadtrace.ops.ai_prefill candidate import /absolute/job/round-2/candidate.json --artifact-root /absolute/managed-artifacts
```

`candidate import` 保存候选，不是应用到科学工作区。API 和审核反馈命令参见 [操作 CLI](../../leadtrace/ops/ai_prefill/README.md) 与 [Preview runbook](../../leadtrace/ops/runbooks/ai_prefill_preview.md)。

## 多 harness 监控记录

每个调用至少记录：run ID、paper key、阶段、轮次、输入/prompt/指南 hash、运行时模型和 harness 版本、工作目录、PID、实际开始/退出时间、退出码、最后日志/文件进展时间、产物文件 hash、技术/科学检查状态、反馈次数及剩余预算。

PID 只是进程定位信息，恢复时还需核对启动时间和命令，避免误认复用 PID。`session_id` 用于终端 `write_stdin`，执行工具的 `cell_id` 用于 `functions.wait`；只有工具返回“Script running with cell ID”时才调用后者。任何等待工具错误，先检查进程与持久产物，不据此宣称 harness 失败或重跑整批。

逐任务实际完成时间必须在各进程退出时记录。按顺序 `wait()` 后计算的 elapsed 会高估后面已结束任务的耗时，本次 `run-results*.json` 就有这个局限。

起始策略：2–3 篇并发，每个阶段调用设显式时间预算，全量阶段可参考本次使用的 30 分钟上限，但按篇幅调整。日志暂时不更新不能直接判死；结合进程、工具调用和文件进展判断。超时只停止属于该 run 的进程组，保留文件和退出原因；不用全局 kill 命令。重启时先恢复已有候选与状态，再决定续跑哪一阶段。

这套记录规范本轮尚未接入自动心跳。若需要跨会话自动运行，应先实现持久任务状态、任务锁、独立退出回收、幂等应用和按事件通知，再扩大并发。

## 如何证明降本增效

比较对象必须采用相同交付标准，例如“进入待人工审核 Preview 且通过同一源图/数值检查”，不能把生成 JSON 与完成审核比较。固定已审核回归集用于防回归，另留新论文评估泛化；旧 CSV 答案不进入新论文提取输入。

下一批建议 6–10 篇，覆盖共享骨架、独立结构图、立体化学、密集 ADME/PK 表和扫描/图像表格。在样本足够前保持 2–3 并发。建议记录：

| 指标 | 分子 / 分母或口径 |
| --- | --- |
| 首轮结构准确率 | 经独立审查正确的结构 / 被审查结构，明确是否全量；疑点单列，不算正确 |
| 修订后结构准确率 | 同上，另列修订仍遗留的问题和遗漏 |
| 数值与条件准确率 | 核对正确的测量项 / 核对项；标明是否包含单位、符号、SD 和条件 |
| 化合物与测量覆盖率 | 已提取身份或原文测量 / 预先调查确认的源项目；不要用候选自身计数作分母 |
| 原图身份覆盖率 | 自身图片足以核对身份的化合物 / 原文存在结构来源的化合物；无图控制药另列 |
| 返工量 | 修订次数、改变的结构/测量/裁剪数量、监督用时、人工复核用时 |
| 单篇总成本 | DeepSeek 各轮 + Codex 监督 + 工具费用 + 人工时间成本；缺少单价或 usage 时不报精确金额 |
| 单位有效产出成本 | 总成本 / 通过相同交付标准的篇数，或经核验的化合物/测量数量 |
| 耗时与吞吐 | 单篇独立起止、监督分钟数、整批墙钟时间、交付篇数；并行时间与劳动时间分开 |

默认科学放行条件：无已知未处理的结构连接错误、无已知错列/单位/符号错误、无伪造来源、无未声明的覆盖缺口；所有保留疑点对审核者可见。用户明确要求查看当前带缺陷结果时，可由监督者按授权写入草稿Preview，绑定候选hash并保留问题记录，仍为needs_revision，不算科学放行。无法确认结构就明确遗漏并连带记录未提取测量/关系，不能用占位 SMILES。疑点可被有说明地交付预览，但不能计为已确认正确。

“出色”的目标应由后续同口径复核和成本数据证明。文档、早期骨架检查、局部反馈和缓存原文渲染有望减少返工；若监督仍需逐单元格重做整篇，费用较低的提取模型也未必降低总成本。

## 交付前 producer 自检

按 [交付前自检指南](deepseek-self-check-guide.md)执行新离线命令 `candidate self-check`。任务包必须复制指南和 `templates/deepseek-self-review.json`，冻结实际文件hash；不改历史任务包。先程序preflight，再DeepSeek逐项回查源文，最后以最终candidate文件hash绑定self-review并复跑。最多两轮修正，未决交partial。退出0仅ready_for_independent_review，不能代替独立审查或Preview批准。该检查尚未强制接入Preview API。
