# AI_prefill：选择入口并恢复实际状态

当前流程 `model-neutral-v4-20261008`，CandidateEnvelope 仍为 v1。日常任务由所选模型连续完成科学生产和自检；测试/指南评估时由 Codex 观察表现、检查确定性产物并调整指南。两种模式采用相同科学标准；生产者自检不能代替新会话中的审查模型独立审查。

## 1. 先确定任务、来源和状态

- 核对 `git status --short`、当前分支和 worktree；使用指定 checkout，不覆盖其他任务改动。只运行预填无需修改业务代码。
- 恢复任务先读运行目录 `HANDOFF.md`、`run-state.json`、任务状态及已有产物。路径取自交接，不按修改时间猜当前运行，不因新对话而重新提取/apply。
- 以外部 catalog/manifest 的 paper key＋DOI 确定源文件，再核对 SHA-256、bytes、pages。所选模型 实际读取 PDF 核验题名/DOI；监督者不读 PDF、源裁图、提取原文或可能含原文的推理日志。
- 新任务目录在忽略的持久 `leadtrace-data/<run-id>/`，保留历史任务包。用户已授权的任务继续执行，不重复索要授权；代码合并不授权生产部署或科学数据导入。
- 质量优先派发前按运行指南核实实际模型、图像能力、thinking/effort 和运行上限，冻结脱敏配置；不凭模型名称或提示词声称“性能开到最高”。从零重跑使用新 source-only 包，保留旧候选和 Preview，不能清空工作区绕过 initial apply。

网页 Admin 可通过[文章管理与 AI 任务控制台](admin-console.md)执行首次生成和新上下文独立检查，查看进度、停止或重试。全站默认并发 4；首次预填正常结束后将可安全保存的候选导入待审核草稿，覆盖缺口和自检未决随任务报告交付，不阻止草稿入库，也不构成科学批准。收回分配保留原草稿，重新开始先归档并创建新工作区。生成／复核报告以分类数量、清单覆盖和逐项复核状态汇总为主；一次新上下文独立复核同时交付原草稿审查和修补方案，查看差异后接受修改。两部分在同一模型会话完成；生成方案不写草稿，接受方案不调用模型；旧版本方案不能覆盖后来的编辑。

## 2. 三个任务入口、两种模式

日常基线是一次生成（含有界自检/内部修正）＋一次新上下文独立复核（核查冻结草稿＋在同一会话生成修补方案）。Admin 的复核任务设置 `review_with_repair=true`；不再单独派发修补调用，接受方案不调用模型，也不自动追加复核。原草稿的独立审查结论和修补后的同会话自检分别记录，不能把修补方案称为再次独立通过。两次 harness 调用中的每次可包含多个 API 请求/工具调用，也不保证全篇正确。无法完成修补时保留有效审查和未决；详见 [调用边界](model-runbook.md#日常调用边界与停止条件)。

| 入口 | 适用情况 | 行为 |
|---|---|---|
| `task prefill` | 从头预填 | 源清点→各结构家族代表核实→全量提取→程序及源自检，保存完整候选与未决 |
| `task review` | 冻结候选的独立复核 | Admin 新任务在同一会话核查并生成单独修补候选；冻结输入不变、审查绑定原候选 hash。历史/CLI 未启用合并契约的任务仍只审查 |
| `task selfcheck` | 已有候选检查/修补 | 验证父候选、源 inventory 和现状；确定增量及依赖；检查/修补并保存新候选，保留未变内容 |

`--mode routine` 是日常模式：所选模型 在一次有界生产调用内推进，不等待 Codex 在每个保存点放行。`--mode evaluation` 用于评测：Codex 监督实际输出、返工和成本；需要冻结中间结果时明确写入任务，不默认复制整套多阶段昂贵流程。独立审查使用新会话中的审查模型上下文，两种模式都不能省略其交付边界。任务目录的 `task.json`/`prompt.md` 保存实际参数和阅读清单，`state.json`/`process.json` 保存执行状态，`inputs/`/`bundle/` 为冻结输入，`outputs/`/`checks/` 为产物与程序检查；run-state/HANDOFF 是上层运行交接。

在工作树根目录运行，绝对路径示例需替换为本次任务值：

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill task prefill --input /absolute/input.json --output /absolute/new-job --mode routine
.venv/bin/python -m leadtrace.ops.ai_prefill task selfcheck --input /absolute/input.json --output /absolute/new-repair --candidate /absolute/current.json --inventory /absolute/inventory.json --feedback /absolute/feedback.json --mode routine
.venv/bin/python -m leadtrace.ops.ai_prefill task run /absolute/new-job --timeout-seconds 1800
.venv/bin/python -m leadtrace.ops.ai_prefill task status /absolute/new-job
```

`--feedback` 可省略。预填和自检入口可提供 `--previous-task /absolute/old-job` 或 `--handoff /absolute/handoff.json` 携带结构化上下文；已产生候选的续修应使用 selfcheck，prefill 仍不提供旧候选/答案作为清点分母。selfcheck 的已有工作区可成对提供 `--workspace-id UUID --workspace-version N` 记录基线，这不会自动联网核验或更新工作区。正式 InputPackage 使用 `target`、`source_locator`、`guide_version`、`recipe`；操作者派发前仍需外部身份对照，可在 recipe 记录预期题名/DOI 与 catalog 来源，不能把旧自定义 `source` 输入当正式包。

`task run` 是一次有界运行器调用（生产或独立复核），每个 job 只运行一次，续修建新 job；本机同一 paper_key（即使 source 不同）保持单写者。它不自动调度独立审查、批准科学结果或 apply。完整流程和产物契约见 [运行指南](model-runbook.md)。

### 按阶段选择模型与推理强度

每个新任务分别传 `--adapter dsh|codex --model MODEL_ID --reasoning-effort LEVEL`，因此预填与独立复核可用不同模型/档位。`selfcheck` 是生产者自检/修补，不能充当独立复核。示例：

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill task prefill --input /absolute/input.json --output /absolute/producer --adapter dsh --model deepseek-flash --reasoning-effort max
.venv/bin/python -m leadtrace.ops.ai_prefill task review --input /absolute/input.json --output /absolute/reviewer --candidate /absolute/producer/outputs/candidate.json --inventory /absolute/producer/outputs/compound-inventory.json --adapter codex --model MODEL_ID --reasoning-effort high
```

`MODEL_ID` 必须替换为本机账号实际可用的模型。参数在 `task.json` 和冻结清单中保存，不能原地改动后重跑；新配置创建新任务。科学规则适用于所有模型。适配器能力、工具、来源标注和交付步骤见 [运行配置](model-runbook.md#runtime-configuration)。

## 3. 恢复生产会话与交接

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill session inspect --run-dir /absolute/job --dsh-home /absolute/dsh-home --output /absolute/session-metadata.json
```

`--dsh-home` 使用实际子进程环境中的 `DSH_HOME` 对应目录，不假设总是 `~/.dsh`。该命令仅支持 dsh，检查会话身份和可获得的 usage 元数据，不把推理内容提供给 Codex。记录真实原生产会话用于追踪。当前 dsh headless CLI 没有原生 resume 参数，继续任务用新 job＋结构化 handoff；不得把新会话写成已恢复旧会话，也不要为恢复而开放 nativeWeb 端口。

`task status` 显示保存的 checkpoint，并报告 `leader_identity_matches`，不是完整实时进程状态。若协调进程退出却遗留 running，执行 `task recover /absolute/job`；它取得同一 paper 锁并核对 boot/PID/start ticks/session 无活进程后才标记 interrupted，不终止进程或重跑。之后引用旧产物建立新 job。

结束前更新 [run-state](templates/run-state.json) 与 [HANDOFF](templates/run-handoff.md)：实际进程/会话状态、输入/候选 hash、已完成范围、独立审查状态、唯一下一步、Preview 版本/回执或 journal、禁止重跑事项、费用未知项。退出 0 和候选文件存在都不代表科学完成。

## 4. 阅读与交付边界

- 科学规则唯一入口：[提取指南](extraction-guide.md)；生产者按阶段读取 [自检指南](self-check-guide.md)，审查者读取 [审查协议](quality-audit-protocol.md)。实际 bundle 完整冻结，角色只读运行指南指定的必要文件，不反复阅读全部操作材料。
- 默认交付文件。写入 Preview 由受信操作者按 [Preview runbook](../../leadtrace/ops/runbooks/ai_prefill_preview.md) 处理；生产者不持有凭据。已有工作区保留人工修改，版本检查＋快照＋差异 journal，不能清空或重置来绕过 initial apply 的空白限制。
- 全文编号/标签身份清点；能找到或合理推导完整结构才写入 Compound。有依据但不确定/冲突的已收录项用统一 review_hint（⚠ 需核对），无法推导的留 inventory required＋omissions，不建空结构卡；测量、结构、SAR、合成分别报告。带缺陷草稿经用户授权可显示，但不能标为科学批准。科学数据、资产和数据库不从 Preview 导入生产。

本机定位线索：持久根 `/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/`，保留 worktree `.worktrees/ai-prefill-tools`，Preview descriptor `ai-prefill-preview-20260920.C191Fl/current-instance.json`。操作前验证当前实例和交接；换机器不执行旧绝对路径，不输出 credentials。
