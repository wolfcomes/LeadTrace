# 新对话执行 AI_prefill：从这里开始

流程版本 `deepseek-supervised-v2+self-check-v1-20260921`。本文件是操作者入口；先执行用户已授权的任务，不重复询问已确定的操作。默认单篇或2–3篇并发，科学内容提取/源审查由DeepSeek，Codex只做监督、确定性检查、反馈组织与报告。

## 1. 先辨认任务与当前状态

1. `git status --short`、`git branch --show-current`、`git worktree list`：区分main和保留的开发工作区。不要在两个工作树同时修改同一功能。只跑预填无需改业务代码。
2. 用户说“继续”时，先读运行目录 `HANDOFF.md`、`run-state.json`、各阶段 `process.json` 和已保存产物；不因新对话就重新提取或重新apply。
3. 用户给论文时，从catalog/manifest按paper key＋DOI确认具体源文件；标题或“最后三篇”不能代替确定的任务列表。可核对hash、bytes、page count，不把原文文本/图像输出给Codex。
4. 独立运行目录必须在本checkout外的持久 `leadtrace-data/<run-id>/` 中或显式指定的安全位置。恢复路径取自HANDOFF，不猜最后修改时间最新的目录就是当前任务。
5. 用户只要求提取/比较时，默认交付文件；请求写入Preview时才进入应用步骤。已有“写入这批Preview”的授权有效，不再要求重复确认。代码合并不等于生产部署授权。

当前这台机器的持久数据根是 `/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/`。保留开发工作树是其相邻 `.worktrees/ai-prefill-tools`，有已安装依赖。当前Preview描述符是数据根下 `ai-prefill-preview-20260920.C191Fl/current-instance.json`，其 `HANDOFF.md` 记录最近刷新。只把这些当定位线索，操作前仍须验证实例与实际状态；不要打印runtime/credentials内容。换机器时必须提供新的数据根/描述符，不能执行这些旧绝对路径。

## 2. 文件与代码职责

```text
repo/
  AGENTS.md                          新Codex自动发现的规则
  docs/ai-prefill/START_HERE.md       当前流程入口
  docs/ai-prefill/prompts/            派发、修订、独立审查模板
  docs/ai-prefill/templates/          自检、质量、运行状态、交接模板
  leadtrace/ops/ai_prefill/            操作者CLI
  leadtrace/backend/app/ai_prefill/   契约/验证/覆盖/自检/Preview/导出
  leadtrace/frontend/src/review/paper/ 化合物、活性、SAR/合成图审阅UI

persistent-data/<run-id>/            不提交Git
  run-state.json                     机器可读的本批范围与逐篇阶段
  HANDOFF.md                         给下一次对话看的当前事实/下一步
  bundle-manifest.json               实际指南/prompt/schema等文件hash
  <paper-key>/
    survey/                          源清单、代表结构、measurement inventory
    core-review/                     新harness源图审查、supervisor gate
    extract/                         candidate、自检、覆盖/结构/路线sidecars
    audit/                           冻结抽样、独立源审查、逐项C/E/U/M
    revision-1/                      如需修订保留父版本，不覆盖旧产物
  preview/                           快照、receipt或明确的更新journal、核验
  report.md                          汇总、具体缺陷、成本与局限
```

目录名是约定，不是已经实现的持久队列。`run-state.json`记录中使用实际绝对路径和完整UTC时间；缺失model/token/金额为null，不能填预计模型名作实际值。

## 3. 准备实际输入包

在仓库根目录用现有Python检查CLI，例：

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill doctor
.venv/bin/python -m leadtrace.ops.ai_prefill contract export --output /absolute/job/candidate-schema.json
```

main没有`.venv`时，使用保留工作树的Python并设 `PYTHONPATH=/absolute/selected-checkout`，或按 `leadtrace/README.md` 创建环境。必须确保实际导入模块来自所选checkout，不能只看Python路径判断代码版本。

每篇拷贝只读源、真实input、外部manifest对照的source-identity-check，以及：

- extraction-guide.md、deepseek-supervised-runbook.md、deepseek-quality-checklist.md；
- quality-audit-protocol.md、quality-pitfalls.md、deepseek-self-check-guide.md；
- candidate-schema.json、通用candidate example、[compound inventory schema](schemas/compound-inventory-v1.json)；
- [source self-review schema](schemas/source-self-review-v1.json)（与自检模板一起分发）；
- templates/deepseek-quality-record.json → quality-record-template.json；
- templates/deepseek-self-review.json → self-review-template.json；
- 填好所有占位符的任务prompt、运行预算及runtime-metadata.json。

`input prepare`生成的正式InputPackage字段是 `target`（SourceIdentity）、`source_locator`、`guide_version`、`recipe`。它不会自动打包指南/PDF，也不会核实实际源身份。candidate_id可放 `recipe.candidate_id` 并明确写入prompt；预期标题和DOI写入独立source-identity-check。历史实验的自定义input可能使用 `source`，不能直接与正式InputPackage混用。派发前检查所用脚本和prompt读的是哪种格式，不往严格schema塞未知字段。

源身份以外部catalog/manifest为参照核对sha256/bytes/pages/DOI；DeepSeek再读PDF确认题名/DOI。冻结所有实际输入文件hash。旧CSV、旧候选答案和旧审查结论不进入新提取目录；复跑时明确是否同文回归，避免误称盲测。

## 4. 分阶段执行与恢复

| 阶段 | DeepSeek负责 | Codex验收后才能继续 |
|---|---|---|
| survey | 全文范围清单、参考物/对照、表/图/正文测量清单、不同骨架代表 | inventory合法、身份匹配、scope和未决明确；不是完整candidate |
| core-review | 新进程实际源图检查代表骨架/区域/立体/连接点 | 逐项已核验核心才允许扩展；未决不伪装pass |
| extract | 全量candidate、原图locators、activity、两类lineage及route-local中间体 | 周期保存；不根据旧答案或编号范围凑数 |
| producer self-check | 按自检指南先程序检查、再源回查、限次修正 | 自检绑定最终文件hash；未决或缺项交partial |
| independent audit | 新进程按冻结样本逐项核查；不得直接修candidate | 重新统计C/E/U/M、缺失/重复slot、实体ref、hash；检查审查自身矛盾 |
| revision（可选） | 根据精确反馈修订及扩大同类缺陷检查 | 保留父版本及差异，复验受影响项目；默认最多两轮 |
| handoff/Preview | 只交文件；不持有Preview写权限 | 报告精确结果；获授权后由监督者执行应用与交付核验 |

通过Python `subprocess.Popen(['dsh', '--profile', 'headless', prompt_text], cwd=stage_dir, stdout=log, stderr=err, start_new_session=True)`启动已安装harness，避免把prompt拼成shell代码。先核实 `dsh --version` 和实际headless配置可用，不输出配置中的密钥。每阶段调用保存PID、开始时间、命令身份、预算、退出码、结束时间和产物路径。需要外部timeout时，只结束该run拥有且核实身份的进程组；日志/产物保留。示例是启动方式，不是通用runner实现。

默认2–3个独立论文进程并发；不要多写者争同一candidate。用户明确要求新窗口时用可用终端/任务窗口承载；headless子进程本身不等于新Codex对话。日志可能含原文内容，Codex只监控大小/更新时间/进程状态，不直接dump推理日志。科学审查结果是允许读取的产物。

开始下一阶段前核实上一阶段真实退出和产物；超时或工具wait报错先恢复已有状态，不盲目重跑。每项审查立即保存，预算到达就交未决。活动Codex对话结束不保证有持续监督；交接时列出仍在运行的进程及恢复方法。

## 5. 必跑检查与统计边界

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate validate /absolute/job/candidate.json
.venv/bin/python -m leadtrace.ops.ai_prefill candidate coverage /absolute/job/candidate.json --inventory /absolute/job/compound-inventory.json
.venv/bin/python -m leadtrace.ops.ai_prefill candidate self-check /absolute/job/candidate.json --inventory /absolute/job/compound-inventory.json --self-review /absolute/job/self-review.json --output /absolute/job/self-check.json
```

`validate`的needs_review可退出0；`coverage`退出4代表required身份缺失/歧义；`self-check`退出4代表确定问题或源自检未完成，退出0仅ready_for_independent_review。所有0都不代表科学批准。自检首次不带self-review为preflight，预期报缺少源自检。

当前机器检查：契约/引用/可解析性、标签coverage、dose误作终点、S.I.单位、重复Activity、lineage分类、自检完整性/hash/真实edge ref。源测量tuple穷尽、原图语义、立体化学、合成条件仍需DeepSeek核实。SAR允许无text evidence；合成路径必须有真实前体关系，中间体可route-local。compound目录以正文/SAR为范围，不能把Methods-only化学形式硬塞入主目录。

每篇固定审查样本在看结果前保存；样本外扩展检查另列。总体分母未知填null；不要从候选自身定义分母，不把SD未核对的数值匹配当整行正确，不把ND当漏提或0。reviewer的“all correct”也须按逐项记录核验。新的源审查进程仍属AI审查，不能叫人工gold。

## 6. Preview写入与可查看状态

Preview数据不导入正式库；代码合并和正式网站更新均不授权复制Preview科学数据。

先读 [Preview runbook](../../leadtrace/ops/runbooks/ai_prefill_preview.md)，由当前descriptor获取profile；检查registry/database实例身份、health、源hash和workspace版本。凭据只由监督者使用，不复制入DeepSeek目录，不打印在日志/最终答复。

- **空白工作区：** candidate import/validation后通过Preview专用API apply，稳定幂等键，保存真实ApplicationReceipt。`candidate import`本身不会写入工作区。
- **已有工作区：** initial apply不支持覆盖；不得清空/重置版本以绕过。局部编辑用已授权Reviewer接口，逐请求版本检查、留前后快照与journal。整篇替换需针对现状制定并执行可恢复方案，确认未覆盖人工编辑；不能机械复制历史实验脚本或伪造新receipt。用户明确要求当前结果写入时，不重复索要授权，但仍须完成这些核验。
- **待修订结果预览：** 用户可明确授权展示带已知缺陷的候选。记录精确hash、问题与授权上下文，所有数据保持draft/needs_revision；“可查看”不等于“科学通过”。没有相应授权时，默认先完成确定性错误修正。

写入后核对实际workspace数据与候选、活动分页、edge草稿、重绘与原图资源可读取；计数和HTTP成功不能代替科学图像验证。旧receipt的changed_since_apply是编辑后的真实状态，后续更新应另留journal/快照。生产环境部署、迁移、发表不属于Preview操作。

## 7. 对话结束前的固定交接

使用 [HANDOFF模板](templates/run-handoff.md) 写实际状态，并更新 [run-state](templates/run-state.json)：

- 本轮论文/源身份、实际代码revision和dirty状态、指南版本与bundle hash；
- 每篇当前阶段、候选路径及文件hash、阶段进程是否已退出、自检/审查状态；
- 已完成结果、具体未决项、下一步**唯一需要执行的动作**与其输入；
- Preview是否已应用、精确实例/工作区版本、receipt或journal、可访问URL；
- 禁止重跑的构建/apply脚本、已存在的人工修改，以及恢复前必须复核的条件；
- tests/实际usage/费用及未知项，清楚区分partial、ready_for_review、needs_revision和accepted。

报告链接到持久目录文件，不能只说“见上一段聊天”。目录有候选不表示已交付，进程exit0不表示科学完成。

## 新对话可直接使用的请求

> 请按仓库AGENTS.md及docs/ai-prefill/START_HERE.md执行AI_prefill。先读取本轮HANDOFF与run-state恢复状态；若新任务则建立独立运行目录。Codex不读原始论文，由DeepSeek harness完成survey、核心审查、提取、交付自检和独立审查。目标论文是[paper keys/DOIs]，运行目录是[绝对路径]。请持续监督至[候选与报告/写入指定Preview并验收]完成，保存跨对话交接文件。
