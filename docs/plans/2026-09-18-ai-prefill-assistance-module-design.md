# AI Prefill 辅助模块设计

创建：2026-09-18。修订：2026-09-19，v2。状态：待评审，尚未实施。

配套工程计划：[工程实施文件](2026-09-18-ai-prefill-assistance-module.md)。

## 1. 结论与首期边界

建设一个可以反复使用的辅助模块：AI 生成标准候选包，工具校验并将选定版本写入独立 Preview DB，人工通过现有 Reviewer UI 判断效果，反馈和修改被保存为下一轮的输入。新进程通过仓库入口文档、结构化任务包和标准命令接手。

首期交付完整的本地实验闭环和专用 Preview HTTP 接口。复用现有科学数据服务、认证和 Reviewer UI。独立远程 Producer 的认证与协议列入下一里程碑；生产应用流程在后续设计评审后扩展。三者共用同一候选契约，不要求首期建完整调度平台。

三个成功标准：

1. 可以把同一论文的 v1、v2 分别放到真实 UI 中检查，知道改了什么、还有什么问题。
2. 关闭当前进程后，新进程只读文档和实验目录，就能恢复工作并找到下一步。
3. 候选提交、校验和应用有明确接口，任何生成器都不能通过直接改数据库来绕过它们。

当前四篇已落入 production 的结果只用于历史核验。首期工程验收在隔离环境进行。

## 2. 对初稿的评估及修正

| 初稿问题 | v2 决策 |
|---|---|
| 26 个任务覆盖调度、租约、审批和新 UI，首期价值太晚出现 | 首期聚焦生成—预览—反馈闭环；远程接入和生产应用独立排期 |
| 新进程上手几乎等同于独立远程 Worker | 区分本地 AI/工程进程、独立 Producer、受信 Operator，分别给入口 |
| Candidate 强制绑定 Paper/Source 数据库 UUID | 跨环境使用 paper_key + source_sha256；目标数据库现场解析 UUID |
| 全部 Evidence 必须有可匹配 quote | 文本自动比对；图、表、Scheme 可以依赖定位并进入人工复核 |
| 四篇被称为 golden/approved，易误解为科学真值 | 定义为历史回归基线；固定 hash 只验证重构没有漂移 |
| 人工在 UI 改好了，却仍批准原 Candidate | 保存原始快照和编辑后快照；修改形成新候选，再验证和预览 |
| Candidate/反馈进入随时会被 reset 的数据库 | 持久实验目录是原始资料；Preview DB 只保留投影和应用凭据 |
| 依赖稳定 ref 做全部 diff，但 Activity 没有 ref | 同时使用 ref、业务键与歧义报告，禁止猜配 |
| 默认反复 drop/reset 同一数据库 | 每轮新建实例；默认保留旧实例；显式清理前导出反馈和编辑 |
| 旧 POST 接口悄然从 apply 改为生成 Candidate | 保留旧接口行为；新工作流采用新增接口 |
| 服务端依赖 ops 目录，部署包可能漏模块 | 契约与服务放 app.ai_prefill；ops 仅作入口和环境编排 |
| CLI 应用成功但报告写失败可能被再次执行 | 数据库内写应用凭据，与科学记录同事务；文件报告可恢复 |
| 端口不同被当作 Cookie 隔离 | 使用独立预览主机名和同源代理；Cookie 不按端口隔离 |
| 工程测试路径、migration 号被直接假定 | 使用已存在路径；实施时按实际 Alembic head 分配 revision |

本次评审依据工作树中的 contracts.py、service.py、router.py、worker_service.py、
config.py、catalog/service.py、workspaces/snapshot.py、auth/router.py、
database.py 和前端 API/路由配置。上述“已有/拟新增”边界应在实施前再次核对。

## 3. 两边的任务与人工角色

| 执行者 | 负责 | 输入与输出 | 权限 |
|---|---|---|---|
| AI Producer，包括本地 AI 任务 | 阅读论文，识别结构/优化关系/活性，根据反馈改进提取 | 输入包与指导 → 候选 JSON、生成记录、未解决问题 | 读取获准的论文和反馈；不持有数据库写权限 |
| LeadTrace 辅助模块，由 Operator 操作 | 准备输入、校验、版本归档、Preview 创建/应用、导出反馈 | 候选包 → 校验报告、Workspace 链接、应用凭据 | 受控读源文件，写指定 Preview DB/asset root |
| 人工 Reviewer | 核对化学含义与实际 UI，标注遗漏/错误，可演示修改 | Preview 与论文 → 评估、编辑快照 | 现有 Reviewer 编辑权限 |
| 独立远程 Producer，第二期 | 通过专用 HTTP 获取授权输入并提交同一契约 | 任务描述 → 候选 | 最小 scope，不获得 Admin 或数据库凭据 |

“新的 AI 进程能上手”首先通过 README、guide、输入包、schema、CLI 和持久状态实现。
不要求本地 AI 先成为长期运行的远程服务。

信任边界不能只写在提示词里：独立 Producer 运行环境不注入数据库凭据。
本地同一 OS 用户若本来可读全部运行配置，就不能声称实现了强权限隔离；
首期这是操作边界，远程接入时再用独立账号/容器落实权限隔离。

## 4. 已有能力与扩展方式

- AiPrefillPayload v1 是科学记录的唯一契约；它允许 image/table/scheme Evidence，也允许空 section。
- AiPrefillService 负责结构解析、Workspace 版本与人工修改检查、事务写入、AI ChangeEvent。
- AssignmentService 负责正常分配与六个 pending section。
- 现有 POST /api/v2/admin/papers/{paper_id}/ai-prefill 仍保留原有排队及 Worker 应用语义。
- 现有 Reviewer 路径 /review/papers/{paperId} 用于人工检查。
- build_paper_snapshot 用于读取完整快照，不能假设它已经是可直接回填的 AiPrefillPayload。
- 当前 CatalogImportService 固定要求 20 篇、manifest_order 1..20。首期复用完整目录基线，
  再选目标文章做实验；任意 N 篇导入属于独立扩展。
- Settings 当前只接受 development/test/production。首期增加 preview 的配置与专用入口限制，
  不可仅把环境变量设为一个当前代码不支持的值。
- backend 安装包只包括 app*。共享业务模块放 app.ai_prefill，HTTP 路由不依赖未安装的 ops。

## 5. 最小数据概念与持久化

首期不新建 Job、Promotion、Evaluation 等全套业务表。

| 概念 | 首期存储 | 用途 |
|---|---|---|
| Experiment | 持久目录 experiment.json | 目标论文、输入版本、当前轮次、工件列表 |
| Candidate | 不可变 envelope + payload | 某次生成的精确内容与 provenance |
| ValidationReport | 追加式报告 | 给定规则/工具版本对 Candidate 的判断 |
| PreviewInstance | 外部 registry + DB marker | 数据库/资产/进程身份及生命周期 |
| ApplicationReceipt | Preview DB 新表 + 可导出副本 | 某 Candidate 已在此实例成功写入的凭据 |
| Evaluation | 持久目录中的版本化反馈 | 人工覆盖范围、问题、快照、后续处理 |

目录布局建议：

~~~
leadtrace-data/ai-prefill/
  experiments/<experiment-id>/
    experiment.json
    inputs/
    candidates/<candidate-id>/candidate.json
    candidates/<candidate-id>/payload.json
    validations/<report-id>.json
    applications/<application-id>.json
    evaluations/<evaluation-id>.json
    snapshots/<snapshot-id>.json
    comparisons/<comparison-id>.json
  previews/<instance-id>/
    registry.json
    runtime/                  # 受保护配置，不进入工件包
    assets/
~~~

Experiment 和 candidate/evaluation 目录不在待销毁的 assets 或 DB 卷内。
每轮只在新目录写入，使用临时目录、完整性校验和原子 rename；并发写入使用锁与唯一 ID。
列表和断点恢复从 manifest/registry 读取，不以 shell history 或“latest”文件作为唯一依据。

## 6. 标准候选契约

增加独立的 CandidateEnvelope v1，内嵌现有 AiPrefillPayload v1。

| 字段 | 要求 |
|---|---|
| envelope_version | 固定 1，与 payload schema_version 分开 |
| candidate_id / experiment_id | 工件身份，接收端验证格式与唯一性 |
| source | paper_key、source_sha256、byte_size、page_count；可含核对用 DOI |
| producer | kind、engine、engine_version、生成时间 |
| recipe | 指导版本、prompt/config digest；实际使用模型时记录可得 model ID |
| parent_candidate_id | 可空，表达修订关系 |
| input_evaluation_ids | 明确使用了哪几份反馈 |
| omissions | 未填 section/记录及原因，不等于论文没有报告 |
| payload | 现有 AiPrefillPayload |
| hashes | 接收工具重新计算，不信任提交者声明 |

source identity 不包含必须跨环境相等的数据库 UUID。Apply 按 paper_key 查询目标，
重新核对 PDF hash/size/page_count，再将本地 UUID 写入 ApplicationReceipt。
找不到、重复匹配、Source 不符必须报错，不按标题模糊匹配。

保存两个不同的 digest：

- payload_sha256：Pydantic v1 model_dump(mode="json") 后，沿用四篇脚本的
  ensure_ascii=True、sort_keys=True、紧凑分隔符、allow_nan=False、UTF-8。
  包含默认字段；保留数组顺序；Decimal 按现有 JSON 序列化处理，不先转 float。
- candidate_sha256：封套内容的 digest，排除自身 hash 字段；绑定 Source、provenance、
  parent、omissions 和 payload。相同 payload 在不同 Source 下不视为同一候选。

Candidate 不携带会变化的“当前有效”状态。重新验证只追加 report；
报告绑定 candidate hash、profile version、validator commit、PDF 提取器/RDKit 版本。
格式不合法的原始提交可以保留在 rejected 输入区，但不能伪装成已解析 Candidate。

生成 JSON Schema 和合法/非法样例；同时提供小型参考 canonicalizer 与 hash 测试向量。
JSON Schema 不能表达全部跨引用及 RDKit 规则，服务端验证始终有最终效力。

## 7. 校验分层：技术可写不等于科学正确

首期只提供一个通用 core-v1 profile；四篇特有校验留在 replay operation 中。

| 层次 | 典型检查 | 结果 |
|---|---|---|
| 契约与可写性 | 额外字段、非法引用、重复 label、恰一结构表示、RDKit、bbox、页码、Source 不符 | error，阻止 apply |
| 科学质量提示 | 缺少 supports、Activity 无 Evidence、遗漏、仅 caption 定位 | needs_review 或 warning，允许 Preview 看效果 |
| 人工判断 | 化合物身份、立体化学、优化因果、Evidence 实际支持、活性条件 | 人工评估记录 |

Evidence 按内容处理：

- 有 quoted_text 时做版本化 Unicode/空白/换行断词规范化，保留数字与有意义符号；
  不使用“删除所有非字母数字”证明数值或化学含义一致。
- quote 未命中、扫描页无文本层、表格读取顺序不稳定均报告 needs_review，
  附页码/定位；不得自动生成替代引文掩盖失败。
- image/table/scheme 可使用 bbox 定位，进行实际 PDF 展示人工核对；不强制伪造 quote。
- 只有 caption 的 Evidence 符合现有契约，但报告定位不足。
- 有 supports link 只能证明关系存在，不能自动证明这段原文支持该 Edge。

Preview 可接受技术有效但质量存在问题的候选，让人看清问题；error 不得绕过。
空 section 允许，必须记录未填原因。当前 Activity.value 是数值，
无法表示的范围/非数值结果先记录 omissions，不塞成 0。
四篇无 Activity 的旧结果不能因此被评为完整或“论文无活性数据”。

## 8. Preview 实例：创建、查看、换轮与清理

### 8.1 默认从干净基线构建

首期使用版本化的 20 篇 catalog manifest + 只读 PDF + Preview 专用账号。
复用导入服务核对 Source，无需复制生产用户、session、审计和审批记录。
目标实验可以只选其中四篇；manifest 缺失或 PDF 不符由 doctor 明确报告。

生产备份恢复不纳入首期常规路径，未来仅用于独立的恢复/兼容验收。

### 8.2 隔离必须真实可验证

- 独立 Preview PostgreSQL 实例优先；runtime 用户无创建/删除数据库权限。
- 数据库名形如 leadtrace_ap_<instance>_preview；外部 registry 记录精确 host/port/db。
- 初始化完成后才写入 DB marker，包含实例 UUID、baseline digest、schema revision。
- 首次 create 仅接受不存在的新目标；缺 marker 的已存在数据库不得被“认领”。
- Preview 资产根与 source 根分离；source 以只读 mount 提供。
- 候选 apply 同步调用服务；首期不启动提取 Celery Worker/beat，禁用 Preview 中旧启动入口，
  防止普通按钮向生产队列派发。
- Preview 使用独立主机名、自己的 session secret，与 API 同源。
  浏览器 Cookie 不受端口隔离；只换端口不是充分隔离。
- 运行入口配置代理 /api、/health 到 Preview backend，打印可打开的 URL。
  现有 Vite 没有这套 proxy，列为明确实现项。
- registry 记录代码 commit、依赖版本、baseline hash、DB revision、URL、进程和实例状态。
  新 worktree 如有 migration，旧实例需新建或显式升级；应用启动本来要求 DB 等于代码 head。

### 8.3 每轮创建一个新实例

~~~
创建实验 → 导入候选 v1 → 校验 → Preview A → 人工反馈
                                   ↓
               修改生成技巧/工具 → 候选 v2 → Preview B → 差异与复核
~~~

v1、v2 必须使用相同 baseline 才能直接比较；代码、规则或 baseline 改变要在报告中标注。
旧实例默认保留，可停机节约资源；新轮次不 drop 旧 DB。

destroy 是显式操作：核对 registry、DB marker、精确目标、关联进程；
先导出 application/当前快照/反馈，验证归档 hash，然后关闭该实例并清理其 DB/assets。
存在未归档编辑或导出失败则拒绝清理。不得提供自动删除用户编辑的默认 force 路径。
导出的工件仍可查看；要恢复旧 UI 可从归档 Candidate 新建实例，历史 UUID 链接会失效，
重新生成链接而非声称旧地址仍可用。

## 9. Apply 事务、重试与报告

新增 Preview ApplicationReceipt 表，唯一约束 (instance_id, idempotency_key)。
包含 candidate/payload/source hash、request digest、Paper/Workspace/run ID、
起止 version、entity map、apply 后快照摘要。另有 Preview marker 表。
这两个小模型是首期必要的数据库支持；不引入新任务调度状态机。

步骤：

1. 读取并校验受管理候选包；参数仅接受 ID，不接受任意服务端路径或 URL。
2. 校验 Preview 身份、权限和 Source；锁定目标 Paper；并发相同请求由唯一约束仲裁。
3. 默认创建新的 Assignment；如果已经有本轮合法的空白 assignment，
   只能按明确 workspace_id + expected_version 选用，不能偷偷复用“最新”。
4. 在同一外层事务 queue/apply；实例化使用隔离 asset root 的 StructureSourceImageService，
   验证真实 crop 和 PDF 显示路径。
5. 任何 applied=False 必须作为失败处理；回滚本轮 assignment/science。
6. 成功后在事务内核对关键不变量并保存 Receipt 与快照，再 commit。
7. commit 后将报告导出到持久目录；独立 verify 复核最终数据库状态。

Preview 的事务后核验遵循同一 core-v1 分层：检查真实写入与候选一致、引用和归属完整；
缺 supports 等已明确的质量问题仍作为 needs_review。不能前置校验允许预览，
后置核验却因相同质量缺口把已提交写入误判为事务失败。

幂等语义：

- 相同 key、相同 request digest 返回同一 Receipt；不重复插入。
- 相同 key、不同内容返回 409。
- commit 后响应丢失或文件导出失败，按 Receipt 恢复；不能误报“未写入”并重跑。
- 事后 verification 失败标为需要检查的已提交结果；不谎称已经回滚。
- 多篇逐篇提交并逐篇保存报告；批次失败列明 committed/failed/not_started。
- 外层事务失败时还需清理本轮新 crop 文件；现有 service 的内部失败清理不能替代外层清理。

映射由写入服务实际生成，不通过查询顺序猜测。无独立 ref 的 Activity/link/member
以 candidate 内 JSON Pointer 映射到行 UUID，并明确只对该 Candidate 有效。
允许用可选字段扩展 AiApplyResult；旧调用不受影响。

## 10. 人工反馈与算法改进

首期复用 Reviewer UI，评估用小型表单模板/CLI，暂不建第二套科学编辑器。

每份 Evaluation 至少记录：

- candidate_sha256、validation report ID、instance/application ID。
- 评估对象：原始 AI 快照，还是人工编辑后快照；分别保存 hash 与 Workspace version。
- 六个 section 的覆盖：reviewed / partial / not_reviewed / not_applicable。
- verdict：acceptable / needs_changes / reject。
- issue：稳定 ID、类型、严重程度、候选 ref 或 JSON Pointer、页码、说明与期望。
- 生成端下一步建议；人工身份与时间。首期文件中的身份是记录，不是服务端认证审批。

不能把“人工修好了”记成原候选 acceptable：

1. 普通反馈不改候选，生成器读明确 evaluation ID 产生 child Candidate。
2. UI 编辑先导出完整 snapshot；仅作解释时保留为反馈附件。
3. 要复用编辑结果，显式 export-candidate：将支持字段映射回 payload、
   为新增记录分配新 ref，保留 human_assisted provenance。
4. 对不能映射的状态或字段给出报告并停止自动转换；不得静默丢失。
5. child Candidate 重新 validate/apply/评估；原始 AI 结果与修正版分别计数。

候选 diff：

- 同一谱系优先 ref；Compound label 可辅助，Structure 的规范化 SMILES仅作提示。
- ref 更名、重复候选、Activity 多 assay 等歧义报告 added/removed/unmatched，
  不凭相似度自动宣布“已修复”。
- Activity 等无 ref 项使用 compound、assay、metric、context 等复合键；
  重复键保留多条，禁止覆盖；数值与单位作为待比较字段。
- 原始 payload diff 与语义 diff 都保留，版本标识明确。
- issue 在下一版 resolved 必须有人确认；AI 只能给 proposed_resolution。

按结构错误、Evidence 错位、关系误判、活性遗漏等汇总，展示复核数量与覆盖率；
没有全面标注真值时，不报告“准确率 99%”一类无依据指标。

## 11. 标准化入口与专用接口

### 11.1 本地 AI / Operator 的标准 CLI（首期）

规范调用为 python -m leadtrace.ops.ai_prefill；仓库根目录配合安装后的 backend。
共享逻辑都在 app.ai_prefill，CLI 不写另一套 SQL。

| 命令族 | 作用 |
|---|---|
| doctor / experiment describe | 读环境与实验状态，给出缺项和下一条命令 |
| contract export / input prepare | 导出 schema、输入包和指导版本 |
| candidate import / validate / compare | 接收 JSON、追加校验、查看差异 |
| preview create / start / stop / apply / verify / destroy | 完整预览生命周期 |
| evaluation template / record / export | 保存结构化反馈和关联快照 |
| workspace export / export-candidate | 归档人工修改；显式生成 child Candidate |

离线 import/validate/compare 不加载生产配置，默认可用 PDF 文件输入，不需要连接 DB。
连接命令必须显式选择受保护 Preview profile；缺配置失败，不回退 Settings 默认数据库。
提供 --json，stdout 只输出机器结果，stderr 输出诊断；错误带 code、field、next_action。

### 11.2 Preview Operator HTTP API（首期）

新增 /api/v2/admin/ai-prefill 前缀；仅在 Preview 能力开启时注册。
复用启用 Admin 的 session、CSRF 和现有权限检查。Producer 不持有该 Admin session。

| 方法与路径（相对此前缀） | 语义 |
|---|---|
| GET /contracts | schema/profile 版本和能力 |
| POST /candidates | 接收 envelope，存受管理工件；201，重放返回同一 ID |
| GET /candidates/{id} | 元数据和已追加的校验报告 |
| POST /candidates/{id}/validations | 不写科学行；返回新 report ID |
| POST /candidates/{id}/preview-applications | 指定 reviewer、目标版本、report、idempotency key，同步 apply |
| GET /applications/{id} | 返回 Receipt、状态和真实 Reviewer 链接 |

首期不通过 HTTP 提供数据库 destroy、production apply 或任意文件访问。
离线 CLI 是授权 Operator 的工具，调用与 HTTP 相同的内部服务与权限/actor 校验。

请求中的 report ID 仅用于指定所看的报告；服务端核对其候选摘要和规则版本，
并在 apply 时重新执行技术检查。不能仅信任磁盘报告中的 valid 字段。

限制请求体大小（本机 M1 实现 2 MiB，按实际流字节计数）、每包最多 5000 个科学对象（含嵌套成员/边）及 PDF 处理耗时；
413 表示体积过大，422 表示契约错误，409 表示身份/幂等/版本冲突。
质量 needs_review 返回报告，不混成 HTTP 500。
不接受客户端指定 artifact path；日志不输出 PDF 原文与凭据。
并发 import 必须原子、同 key 不同内容冲突；源文件 hash 在 apply 时再核对。

### 11.3 独立 Producer API（第二期，保留范围）

后续新增 /api/v2/ai-prefill/producer：

- 领取/读取已授权任务与输入；
- 按任务授权读取 Source、反馈、validator report；
- 提交同一 CandidateEnvelope；
- 获取提交回执；可报告失败。

第二期先按指定 task ID 工作。只有实际需要多个 Worker 自动抢任务时，
再加 lease、heartbeat、能力调度；不提前复制现有 Celery/reconciler。
认证采用独立可撤销 token，绑定 producer 和 task scope；不能执行 apply。
schema/CLI 输出错误语义与本地保持一致。OpenAPI 和独立进程 conformance test 为交付物。

现有 Paper-level POST 和 Worker 不静默改语义；迁移时另行定义开关、兼容测试和下线计划。

## 12. 不依赖记忆的指导包

交付三类文档，分别回答三个问题：

| 文档 | 读者与内容 |
|---|---|
| ops/ai_prefill/README.md | 新 Operator/开发任务：安装、doctor、状态、预览命令、恢复 |
| docs/ai-prefill/extraction-guide.md | AI Producer：科学提取顺序、工具使用、证据与不确定性处理 |
| ops/runbooks/ai_prefill_preview.md | 环境管理员：启动/停止、URL、账号来源、归档和清理 |

extraction-guide 必须包含具体技巧：

1. 先确认论文/补充材料范围和 PDF 实际页号，建立 Compound label 清单。
2. 对结构检查环系、连接点、立体化学、盐和电荷；RDKit 可解析不能证明和原图一致。
3. 用文字论述/表格/合成路线定位关系；不能把合成中间体顺序直接视作优化因果。
4. 为每条关系保留证据位置；引文与推理分开，缺证据时留待核对。
5. 活性先确认 assay、指标、比较符、单位、实验条件；无法表示则记录遗漏原因。
6. 运行工具获得真实报告，按错误修复；不能为了通过校验而改 Source 标识、伪造引用。
7. 输出最小合法样例、常见错误反例及反馈驱动的第二轮示例。

输入包包括：实验目标、Source hash/page count、获准读取方式、schema、
指导版本、生成 recipe、parent Candidate 和 Evaluation IDs。
不强制使用某模型；模型、OCR、结构识别工具实际用到才记录相应版本和可复现配置。

提交可跟踪的最小根 AGENTS.md 入口指针（若已有则仅追加模块入口）；
详细说明只有一个权威版本，避免复制矛盾指南。
新进程验收从干净 shell 开始，不加载历史对话，不依赖其他 worktree 的 .venv。

## 13. 四篇历史回归与生产边界

固定源：004 / 005 / 010 / 013，历史 payload 数量：
Compound/Structure 11/11、41/41、6/6、10/10；
Lineage 1、5、1、1；Edge/Evidence/link 6、35、5、8；Activity/locator 为 0。

四篇 canonical hash 见现有 dry-run manifest，首次转换先原样留档。
这些 hash 是重构兼容检查，不是科学质量背书。
提取器改进允许出现新 hash、新 count，必须生成新 Candidate、diff 和 Evaluation。
不要让泛化工具永久拒绝与旧四篇计数不同的正确结果。

现有 quoted Evidence 和真实 payload 迁移到受保护实验目录；
Git 只保留公开元数据、digest 和合成测试夹具，不新增论文大段原文。
旧脚本保持历史可核验，首期不重构其生产 apply 路径。

后续 production 只导入明确选定的 Candidate，不在应用时重新提取。
在生产侧重新解析 paper_key + source_sha256、核对空白状态、当前备份和人工授权。
文件 hash 只能证明完整性，不能证明审批人身份；不能把 Preview 文件 verdict 当生产授权。
已有四篇如需科学修订，走 Reviewer 编辑；替换成功预填另行设计，不能删记录重跑。
生产上线本身涉及 migration/配置与兼容验证，当前方案修订不授权部署。

## 14. 交付顺序与验收

| 里程碑 | 可用结果 | 验收边界 |
|---|---|---|
| M1 当前实施候选 | 标准候选/指导包、CLI、Preview API、真实 UI、反馈与版本比较 | 本地新进程独立走完 v1→反馈→v2；四篇回放；旧接口回归 |
| M2 独立 Producer | task scoped 认证、输入/提交/反馈 API、OpenAPI | 无仓库 import、无 DB 凭据的进程完成一轮 |
| M3 生产与易用性 | 按需评估 UI、生产导入授权与受控应用 | 单独设计评审、部署与恢复验证 |

M1 不以 M2/M3 全部完成为交付条件，也不把“执行计划”理解为自动实施所有阶段。

关键验收：

- 同源登录、Source PDF、结构图、Lineage、Evidence 页面可实际打开。
- v2 使用相同基线；v1 的人工反馈和修改在旧实例清理后仍存在。
- UUID 不同的两个 Preview 能应用同一个 Candidate。
- 图表 Evidence 和无 Activity 的候选可检查，质量缺口明确。
- UI 修改后不能误批准原结果；导出 child Candidate 后可再次预览。
- DB commit 后进程中断可由 Receipt 恢复，重复请求不重复写。
- 身份不符、已有人工记录、Source 漂移、非法结构等失败有明确报告。
- 接口、工具、指导和版本记录足以让新进程独立工作。

## 15. 当前建议默认值

这些是可修改的设计默认值，不要求在写代码前讨论所有远期问题：

- 首期单操作者、同步 apply、一套实验目录；每轮新建 Preview 实例。
- 20 篇 catalog seed，四篇回放；后续再支持任意 N 篇。
- 人工评估先用结构化文件与现有 UI；不建完整评估平台。
- 专用 Preview API 首期交付；远程 Producer token/API 第二期交付。
- 生成 recipe 和输入上下文持久化；科学不确定性允许显式保留。
- 当前文档为待评审草案；后续编码按 M1 的具体验收推进。
