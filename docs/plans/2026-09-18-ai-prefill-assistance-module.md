# AI Prefill 辅助模块工程实施计划

创建：2026-09-18。修订：2026-09-19，v2。状态：2026-09-20 M1 本机实现及真实 UI 技术迭代完成；自动化反馈、导出、v2 再应用和归档恢复已验证，用户最终科学审核待进行。

**Goal:** 先交付可重复运行的 AI 候选生成、真实 Preview 检查、人工反馈与再生成闭环，
同时提供标准契约、专用 Preview API 和不依赖历史对话的操作指导。

**Architecture:** 核心放在 app.ai_prefill，CLI/HTTP 共用服务。
不可变 Candidate/Evaluation 保存到独立实验目录，Preview 数据库只承载正常科学记录、
环境标记和事务应用凭据。后续远程 Producer 与生产应用复用同一契约。

**Tech Stack:** 现有 Python 3.12、Pydantic、FastAPI、SQLAlchemy、Alembic、PostgreSQL、
PyMuPDF、RDKit、Vue、pytest、Vitest、Playwright；首期不增加调度框架。

设计依据：[设计文件 v2](2026-09-18-ai-prefill-assistance-module-design.md)。

## 1. 执行边界与阶段

M1 是本次可评估、可独立交付的实施范围。M2/M3 是后续路线，不能在 M1 完成后自动开工。
本文给出文件、行为、测试及验收顺序；尚未确认的业务判断不得通过代码悄然决定。

- 开发分支 codex/ai-prefill-tools，worktree .worktrees/ai-prefill-tools。
- 不重跑四篇 production apply，不部署 production migration。
- 保留旧 Paper-level API 的调用语义与 Worker 行为；仅在 Preview 禁用其提取入口。
- 不重构历史四篇生产脚本的写入流程，只读取其元数据用于兼容测试。
- 所有新增 runtime 核心位于 backend 安装包 app* 内；ops 为薄 CLI/环境编排。
- 用户已授权在指定 worktree 继续实施 M1；当前验证证据与未完成项见 [验收记录](../ai-prefill/verification-2026-09-20.md)。
- 使用有价值的失败测试验证行为，重点测身份、引用、事务、UI 和恢复；
  不为 README 的每一句话编写脆弱测试，不执行文档里的任意 shell 文本。
- 每个任务完成时审阅 diff、运行相关检查；阶段内提交保持可审查，合并需另行决定。

## 2. 先建立可复现开发环境

以下是实施环境命令模板；已有可用虚拟环境时直接使用，不重复创建。
从 worktree 根目录运行，使用本 worktree 的独立虚拟环境：

~~~bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e 'leadtrace/backend[test]'
cd leadtrace/backend
../../.venv/bin/python -m pytest tests/ops/test_prefill_four_production_examples.py tests/ai_prefill tests/workspaces/test_assignment.py -q
~~~

执行 pytest 前在受保护 shell profile 中设置 LEADTRACE_TEST_DATABASE_URL。
必须先连接核对实际数据库名以 _test 结尾，并确认 host/port 指向隔离测试实例。
测试 fixture 会 DROP public SCHEMA；同一测试库的数据库测试必须串行。
Preview 生命周期集成测试使用独立临时 PostgreSQL cluster（本轮为 native），
在该 cluster 内创建 _preview 数据库；不能套用会重置 public 的通用 test fixture。

实施前重新检查：git status、适用 AGENTS.md、实际 Alembic head、受保护的
catalog manifest/source 配置。不给任务预分配 0026/0027/0028，避免与其他分支冲突。

主要已有入口：

- leadtrace/backend/app/ai_prefill/{contracts,service,router,worker_service}.py
- leadtrace/backend/app/catalog/service.py（固定 20 篇 manifest）
- leadtrace/backend/app/workspaces/{assignment,snapshot}.py
- leadtrace/backend/app/structure_images/service.py
- leadtrace/backend/app/database.py（动态验证 Alembic head）
- leadtrace/backend/tests/security/test_route_permission_matrix.py
- leadtrace/frontend/src/api/client.ts（同源请求）
- leadtrace/frontend/src/app/router.ts（/review/papers/:paperId）

下文除明确标注“已有/Modify”外，文件均为拟新增；实施时每项创建前检查冲突。

## 3. M1 的依赖顺序

~~~
T1 契约/基线 → T2 工件 → T3 校验 → T4 输入/指导/CLI
                                      ↓
T5 Preview 身份与凭据 → T6 创建与站点 → T7 apply/恢复
                                              ↓
                              T8 专用 API → T9 反馈/导出/diff
                                              ↓
                              T10 清理 → T11 文档/冷启动验收
~~~

T5 与 T1–T4 可以独立设计，但此计划不要求并行代理实施。
M1 完成门槛是一次完整真实 UI 迭代；无需先实现远程 Worker。

### T1：确定契约和四篇历史回归基线

**文件**

- Create: leadtrace/backend/app/ai_prefill/assistance_contracts.py
- Create: leadtrace/backend/tests/ai_prefill/test_assistance_contracts.py
- Create: leadtrace/ops/ai_prefill/operations/four_production_examples_20260918.json
- Create: leadtrace/backend/tests/ai_prefill/fixtures/assistance/（合成例子）
- Read only: leadtrace/ops/pilot/prefill_four_production_examples.py
- Read only: 受保护的 dry-run manifest 与四份 payload（本地可选回归资料）

**实施与测试**

1. 测试跨环境身份：paper_key/hash/size/pages 相同、DB UUID 不同仍可映射；
   UUID 不作为 Candidate 必填字段。
2. 定义 Envelope、SourceIdentity、Provenance、Omission、ValidationReport、
   Evaluation、Experiment/Instance registry。拒绝额外字段和未知版本。
3. 内嵌已有 AiPrefillPayload，不复制科学模型。
4. payload canonicalization 精确沿用历史实现；明确 Decimal、默认值、Unicode、
   数组顺序、非法浮点和自身 hash 排除规则；给参考测试向量。
5. 分别测 payload_sha256 和 candidate_sha256；Source/provenance 改变只允许后者随之变。
6. 回归清单只含 paper keys、摘要、counts 和 Source metadata。
   真实引文/完整 payload 不复制到 Git。缺少私有材料的测试明确 skip，
   合成契约测试仍必须执行，不能把 skip 当四篇回归通过。
7. 四篇 hash 以原有 manifest 为依据，记录原样重构是否一致；
   新提取版本允许产生不同 hash，并生成 diff。

**验收**：契约支持未知/遗漏说明；不把历史结果声明为科学 ground truth。

~~~bash
cd leadtrace/backend
../../.venv/bin/python -m pytest tests/ai_prefill/test_assistance_contracts.py tests/ai_prefill/test_contract.py -q
~~~

### T2：不可变工件与断点恢复

**文件**

- Create: leadtrace/backend/app/ai_prefill/artifact_store.py
- Create: leadtrace/backend/tests/ai_prefill/test_artifact_store.py

**实施与测试**

1. 定义唯一 artifact root；实验、候选、报告目录只接受合法 ID。
2. 临时写入、fsync、manifest 校验、原子发布；不可覆盖已有 Candidate。
3. 同 submission key/同内容返回原 Candidate；同 key/异内容冲突。
4. 追加式 validation/evaluation；跨进程锁避免清单丢更新。
5. 测绝对路径、../、symlink、同 ID 冲突、并发和写中断。
6. 清理实例目录不能触及 experiments 目录；新增 orphan 检查不自动删除资料。
7. 不把远程 URL 或用户给定服务端路径当工件定位器。

**验收**：两个进程可先后读取同一实验并恢复下一步；无“latest”单点依赖。

### T3：通用校验与 Evidence 的人工复核路径

**文件**

- Create: leadtrace/backend/app/ai_prefill/assistance_validation.py
- Create: leadtrace/backend/tests/ai_prefill/test_assistance_validation.py
- Modify（如有必要）: leadtrace/backend/app/structures/service.py
- Modify（对应共享解析入口）: leadtrace/backend/app/ai_prefill/service.py

**实施与测试**

1. 技术 error 阻止 apply：Source 漂移、越界、无效结构、双表示、引用/bbox 错误。
2. 质量 needs_review 保留可视化能力：缺支持链、Activity 无 Evidence、
   OCR/quote 未命中、仅 caption、不完整 section。
3. 引文规范化不得消除 <、>、小数点等科学语义；测扫描页、连字符、Unicode 和表格。
4. 测 bbox-only scheme/image 可以 Preview，且报告人工核对项。
5. DOI 缺省可接受；与源标识冲突报告问题，不修改源身份来通过。
6. 如需公共结构解析入口，最小提取已有实现；禁止新增另一套 RDKit 规则。
7. report 绑定 Source hash、candidate hash、profile/version、库版本。
8. validate 不创建科学记录；带 PDF 输入的离线命令不启动 DB bootstrap。

**验收**：合法但科学质量不佳的候选可在 Preview 检查，错误数据不能写入。

### T4：输入包、提取指导与离线 CLI

**文件**

- Create: leadtrace/ops/ai_prefill/{__init__,__main__,cli}.py
- Create: leadtrace/backend/app/ai_prefill/assistance_inputs.py
- Create: leadtrace/backend/tests/ai_prefill/test_assistance_inputs.py
- Create: leadtrace/backend/tests/ops/test_ai_prefill_cli.py
- Create: docs/ai-prefill/{extraction-guide,error-catalog}.md
- Create: docs/ai-prefill/schemas/（由 Pydantic 生成）
- Create: docs/ai-prefill/examples/（合成最小输入/候选/反馈）

**实施与测试**

1. 实现 doctor、experiment describe、contract export、input prepare、
   candidate import/validate/compare 的 parser 和机器输出结构。
   尚未实现的子命令明确 unavailable，不返回假成功。
2. 输入包绑定 Source、guide/recipe 版本、parent、具体 feedback IDs；
   本地 Source 路径仅出现在授权输入 locator，不进入对外 provenance。
3. 支持 AI 新生成的 JSON 和 legacy 适配输入，两者都走相同接收与校验。
4. 指导必须覆盖结构核对、合成与优化关系区分、PDF 页号、活性单位、
   不确定性和遗漏记录，提供第二轮修订例子。
5. doctor 默认离线；DB 检查必须显式 profile，显示脱敏目标和缺项。
6. stdout 结构化输出，stderr 日志；不加载生产配置，不隐式用默认 DB URL。
7. 运行 --help 和合成 Candidate import/validate；这是 smoke test，
   不自动执行 Markdown 代码块。
8. 错误码约定：0 成功，2 契约/输入，3 环境不符，4 校验 error，
   5 执行失败；needs_review 出现在报告中，不当作技术失败。

**验收**：新的本地 AI 进程能仅凭输入包、guide 和 CLI 生成/提交结果。

### T5：Preview 身份及数据库内应用凭据

**文件**

- Modify: leadtrace/backend/app/config.py
- Create: leadtrace/backend/app/ai_prefill/preview_models.py
- Create: leadtrace/backend/app/ai_prefill/preview_identity.py
- Modify: leadtrace/backend/app/db/model_registry.py
- Create: leadtrace/backend/migrations/versions/<actual_revision>_ai_prefill_preview_receipts.py
- Create: leadtrace/backend/tests/ai_prefill/test_preview_identity.py
- Create: leadtrace/backend/tests/ai_prefill/test_preview_receipts.py
- Modify: leadtrace/backend/tests/db/test_migrations.py

**实施与测试**

1. 检查实际 head 后创建一条追加式 migration，不修改 ai_extraction_runs 现有状态。
2. preview marker：instance_id、baseline_sha256、created_at；
   外部 registry 同时记录部署 host/db/schema/资产身份。
3. receipt：instance_id、application_id、idempotency_key、request_digest、
   candidate/payload/source hash、paper/workspace/run ID、actor、
   entity map、初始 snapshot、版本和 committed_at。
4. 唯一约束 instance/key；paper/workspace/run 的关联保持一致，
   committed receipt 和科学记录同事务。
5. Settings 显式支持 preview，独立 artifact_root、deployment profile；
   不能让 preview 的存在绕过既有 production 设置校验。
6. apply 前核对 current_database、DB marker、registry 和 asset root；
   仅数据库名后缀不能作为充分条件。
7. 测旧 migration → 新 head，旧 API 模型和状态仍可运行；
   runtime 启动时不得自动迁移。

**验收**：可辨认实例、可查已提交应用；不需要新 Job/Promotion 表。

### T6：可启动的 Preview 站点与实例创建

2026-09-20 进度：native 后端创建、独立 runtime role、20 篇 seed/账号、start/status/stop 已实现，本轮完整回归 256 项通过。完整前端同源站点、Compose provisioning、只读挂载及浏览器验收仍未完成；详见 `docs/ai-prefill/verification-preview-provision-2026-09-20.md`。

**文件**

- Create: leadtrace/ops/ai_prefill/preview_runtime.py
- Create: leadtrace/deploy/compose.ai-prefill-preview.yaml
- Create: leadtrace/deploy/env/ai-prefill-preview.example.env
- Create: leadtrace/deploy/nginx/ai-prefill-preview.conf
- Create: leadtrace/backend/tests/ops/test_ai_prefill_preview_runtime.py
- Modify: leadtrace/backend/app/ai_prefill/router.py
- Modify: leadtrace/frontend/src/app/AppShell.vue
- Modify: leadtrace/frontend/src/v2/types.ts（如果展示环境需要能力投影）
- Create/Modify: 最小 environment/capabilities 投影及其测试（不输出配置秘密）

**实施与测试**

1. create 只创建不存在的新数据库/目录；初始化中断留下 incomplete registry，
   可继续核验或显式清理，不能假装初始化完成。
2. 使用独立 PostgreSQL 实例/受限 runtime role；
   创建数据库用独立 provisioning 凭据，不注入 Web/Producer。
3. migration 后导入完整 20 篇 catalog seed，创建 Preview-only 账号。
   不改变现有导入器的“恰好 20 篇”约束；选目标 paper_key 作为实验范围。
4. read-only source mount，独立 asset root/session secret。
5. 首期同步 apply，不启动 Celery/beat；
   Preview 中旧启动按钮/API 返回明确 blocked_reason，production 行为保持。
6. 单一可访问 Preview origin 通过代理提供前端、/api、/health；
   使用可解析的独立主机名，HTTPS/cookie 设置与部署一致。
7. 工具输出登录入口、Reviewer 链接、账号获取方式；
   不在 JSON 报告或日志输出密码。
8. 展示明显“预览环境”标记，避免用户误认正式站点。
9. start/stop 验证实例与进程归属；资源名、端口冲突时失败，
   不 kill 同端口的未知进程。
10. 核对健康检查、登录、真实 PDF 访问；记录 commit、lockfile digest、
    baseline 和 schema revision。

**验收**：浏览器能登录并看到源 PDF，生产登录不被影响。

生命周期测试必须在独立临时 PostgreSQL/Compose 项目进行；
环境没有 Docker/等价独立运行时则报告具体缺项，不连接现有生产数据库兜底。

### T7：事务 apply、映射、裁剪和提交后恢复

**文件**

- Create: leadtrace/backend/app/ai_prefill/preview_application.py
- Create: leadtrace/backend/app/ai_prefill/assistance_verification.py
- Modify: leadtrace/backend/app/ai_prefill/service.py
- Create: leadtrace/backend/tests/ai_prefill/test_preview_application.py
- Modify: leadtrace/backend/tests/ai_prefill/test_apply.py
- Modify: leadtrace/ops/ai_prefill/cli.py

**实施与测试**

1. 对无 assignment 的 Paper 原子创建 assignment/queue/apply/receipt；
   已有空白 Workspace 仅明确 ID/version 才可选用。
2. Paper 行锁与 receipt 唯一约束保护并发；同幂等 key 返回同一次应用。
3. payload/source/validation 身份 apply 前复核；所有 source/candidate 字节被固定，
   避免校验后读取到替换文件；篡改磁盘报告的 valid 字段不能绕过实时技术检查。
4. 可选扩展 AiApplyResult 返回实际映射；无 ref 项以 Candidate JSON Pointer 为键。
5. 传入配置正确的 StructureSourceImageService，覆盖非零 locator 的图像生成测试。
6. 验证外层回滚也清理本轮 crop 资产，不能只测 service 内 nested transaction。
7. 在 commit 前保存 receipt、初始 snapshot，核对计数、归属、AI event、版本与 pending sections；
   写入后的结构规范化差异通过标准化投影比较，不要求 DB 原始字节等同 payload。
   前后校验使用相同质量分层，已知 needs_review 不能在 commit 后被误报为写入失败。
8. 注入 commit 后响应/文件导出故障；重试只导出既有 receipt，不产生第二次写入。
9. 独立 verify 只读数据库，可以另存报告；人工编辑后应返回 changed_since_apply，
   与“原始 apply 完整性失败”区分。
10. 多篇逐篇报告 committed/failed/not_started，不宣称跨篇全局回滚。

**验收**：成功、失败、并发、进程重启、裁剪失败都能说明数据实际状态。

~~~bash
cd leadtrace/backend
../../.venv/bin/python -m pytest tests/ai_prefill/test_preview_application.py tests/ai_prefill/test_apply.py tests/workspaces/test_assignment.py -q
~~~

### T8：首期专用 Preview HTTP API

**文件**

- Create: leadtrace/backend/app/ai_prefill/assistance_router.py
- Create: leadtrace/backend/app/ai_prefill/assistance_schemas.py
- Modify: leadtrace/backend/app/main.py
- Create: leadtrace/backend/tests/ai_prefill/test_assistance_api.py
- Modify: leadtrace/backend/tests/security/test_route_permission_matrix.py
- Create: docs/ai-prefill/openapi-preview.json（生成的受审契约）

**实施与测试**

1. 实现设计 §11.2 的六个端点：contracts、候选接收/读取、validation、
   preview-applications、application 查询。
2. 复用 Admin session/CSRF；只在 Preview 注册。
   Candidate 提交不得创建 Workspace 或科学行。
3. 路由只调用共享服务；CLI 和 HTTP 输入得到相同校验结果。
4. 拒绝任意服务器路径/URL，验证 ID、体积和对象数上限。
5. 同 key 同输入重放；异输入 409；技术错误 422；
   needs_review 报告保留；无权限/CSRF 被拒。
6. API 返回的 Reviewer URL 实际路由可用；不给 producer Admin token。
7. production 中新增 Preview endpoints 不可用，旧 endpoint 仍可正常排队；
   跑已有 test_api/test_worker/test_recovery，确保未暗改语义。
8. OpenAPI 中注明 v1 envelope、hash 算法、错误格式和请求样例。

**验收**：标准专用接口首期可用；不把“专用接口”全部推迟到远期。

### T9：反馈、人工编辑导出与 Candidate diff

**文件**

- Create: leadtrace/backend/app/ai_prefill/assistance_evaluation.py
- Create: leadtrace/backend/app/ai_prefill/assistance_compare.py
- Create: leadtrace/backend/app/ai_prefill/workspace_export.py
- Create: leadtrace/backend/tests/ai_prefill/test_assistance_evaluation.py
- Create: leadtrace/backend/tests/ai_prefill/test_assistance_compare.py
- Create: leadtrace/backend/tests/ai_prefill/test_workspace_export.py
- Modify: leadtrace/ops/ai_prefill/cli.py

**实施与测试**

1. Evaluation 绑定 candidate、report、application、source、评估时 snapshot/version。
2. 六个 section 的 reviewed/partial/not_reviewed/not_applicable，
   未覆盖关键项不能标为完整 acceptable。
3. 原始 AI 快照与人工编辑快照分开；Workspace 已编辑而声称原结果 acceptable 则报错。
4. export 快照前验证期望版本；并发编辑检测失败可重试，不能混合两个版本。
5. export-candidate 映射科学字段；新增记录创建新 ref，AI/human provenance 明确。
   不可表示的内容列出并拒绝自动导出；绝不直接将 build_paper_snapshot 当 payload。
6. child Candidate 经校验、全新 Preview 再应用；原 Candidate hash 不变。
7. diff 先 ref/业务键，重复 Activity、多 assay、ref 更名、对称边等歧义显式报告。
8. 模型只建议 issue resolution，人工确认；生成 recipe 引用本次 feedback。
9. 生成简单 Markdown 评估摘要供用户读；无需新增完整评估 UI。

**验收**：人修好的结果不会被误记成 AI 原始结果；反馈可被新进程准确消费。

### T10：归档与精确清理

**文件**

- Create: leadtrace/ops/ai_prefill/preview_cleanup.py
- Create: leadtrace/backend/tests/ops/test_ai_prefill_preview_cleanup.py
- Modify: leadtrace/ops/ai_prefill/cli.py

**实施与测试**

1. destroy 先只读列出精确 DB/assets/进程和归档状态，要求 instance ID 确认。
2. registry 与 DB marker 双重匹配；不接受“名称像 preview”作为唯一依据。
3. 导出 receipt、快照、编辑与反馈并验证摘要；失败或未归档修改阻止删除。
4. 停止本实例后删除精确受管资源；不跟随 symlink、不删除上级目录、
   不依赖通配符、不删除 experiments。
5. 测 registry 丢失、marker 不符、初始化失败、归档失败、未知进程、
   同名其他实例、重复 destroy 和半途失败恢复。
6. 归档后可关闭全部 Preview 实例，再用相同 Candidate 重建 UI，
   返回新的有效链接；历史链接明确 archived。

**验收**：两轮人审记录和工件在清理后仍完整，不自动丢弃人工编辑。

### T11：入口文档、冷启动和真实人工验收

**文件**

- Create: leadtrace/ops/ai_prefill/README.md
- Create: leadtrace/ops/runbooks/ai_prefill_preview.md
- Create/Modify: AGENTS.md（仅 canonical 入口指针）
- Modify: leadtrace/README.md
- Create: leadtrace/backend/tests/ops/test_ai_prefill_cli_smoke.py
- Create: leadtrace/frontend/e2e/ai-prefill-preview-live.spec.ts
- Create outside Git: 实验验收工件

**实施与测试**

1. README 从全新 shell/worktree 的依赖安装开始；
   提供 doctor、生成、预览 URL/登录、反馈、第二轮、恢复与清理。
2. 每个例子明确“已有命令/拟实现命令”，完成时清除不可执行的示意命令。
3. guide 包含工具与科学技巧、合法和非法样例，error catalog 给 next_action。
4. smoke 测试仅执行固定已知命令，验证 --help/--json/脱敏输出，
   不解释运行 Markdown 中任意命令。
5. live E2E 使用真实 Preview backend/database，不 mock /api；
   现有 mock UI tests 只证明前端投影，不能替代本步骤。
6. 人工查看 PDF、Compound/Structure、Lineage、Evidence 和遗漏说明；
   四篇历史 hash 回放可证明兼容，不能替代科学复核。
7. 用一个合成缺陷或真实发现的问题产生 v2，展示 diff 与 issue 复核。
8. UI 实际修改一条记录，导出 child Candidate，再在新实例预览。
9. 关闭原进程后，由无历史对话的新任务仅凭入口资料恢复实验。
10. 清理一个旧实例，确认反馈/修改/候选均可读且新实例仍工作。
11. 记录经过检查的功能、未核对的科学范围和具体故障，不以测试数量替代验收。

**最终验证命令（实现后）**

~~~bash
cd leadtrace/backend
../../.venv/bin/python -m pytest tests/ai_prefill tests/ops tests/workspaces/test_assignment.py tests/security tests/db/test_migrations.py -q
../../.venv/bin/python -m compileall -q app
cd ../frontend
npm ci
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e:preview  # 需设置 PREVIEW_LIVE_ORIGIN/CREDENTIALS_FILE/PAPER_KEY，见 runbook
cd ../..
# Compose 未作为本轮验收部署；native lifecycle + 真实浏览器完成部署验证
git diff --check
~~~

Playwright 的项目/配置需显式包含新增 live 文件；
连接 profile 必须由测试入口验证为专用验收实例。
若项目测试配置需要单独 live config，在该任务创建并更新上述命令。
不把局部单元测试通过称为真实 UI 验收通过。

## 4. M1 完成定义

必须全部可演示：

- CLI 与专用 HTTP 接口使用同一候选契约和核心服务。
- 新环境 UUID 不影响同一 Source 候选导入。
- 真实 Preview 可以登录、打开 PDF、显示结构和 Evidence。
- 技术有效但质量待改的结果可以查看，问题和遗漏显式保留。
- v1 → 人工反馈 → v2 → diff → 再评估完整走通。
- UI 修订导出不混淆原始 AI 与人工贡献。
- apply 重放不重复写；commit 后崩溃可由 Receipt 恢复。
- 旧实例清理不丢工件/反馈，未知实例不被误清理。
- 从新 shell 依照文档可接手，无其他 worktree 环境依赖。
- 旧 API/Worker 测试通过；生产环境没有因验收发生写入。

M1 只完成到上述范围即可交付评审，不以新审批系统或完整远程调度为前提。

## 5. M2：独立 Producer 接入（后续，不自动实施）

前提：M1 经一次实际迭代，Candidate 和错误语义已稳定。

### M2.1 最小任务授权与认证

- 在 app.ai_prefill 增加 producer_task、producer_auth 服务与测试。
- 任务由 Operator 指定 paper/source/recipe/feedback；
  token scope 绑定任务与 Producer，可撤销、到期，服务端只存安全摘要。
- migration 按当时 head 分配，配套模型注册与路由权限矩阵。
- 首版不自动抢任务；只有出现并发 Worker 需求才设计 claim lease。

### M2.2 专用输入、提交与报告接口

- 新增 /api/v2/ai-prefill/producer 的 task read/source/feedback、
  candidate submit/receipt、fail 接口。
- Source 按授权范围流式读取，不返回服务器路径；
  提交 key 绑定任务，重复请求幂等，不可应用 Workspace。
- 合法 Candidate 共用 M1 接收与校验模块；不复制逻辑。
- 失效 token、跨任务读取、超大 payload、提交后响应丢失、重复 submit 均有测试。
- 现有 Worker 是否接入另作兼容选择；任何迁移保留旧 API 合约，
  不将原来的 succeeded 偷换成“仅生成成功”。

### M2.3 独立进程一致性验收

- 给无 repository import/无 DB 凭据的进程 OpenAPI、JSON Schema、样例和任务 token。
- 完成读取、生成、提交、反馈查询；
  首次输入错误与第二次修正都可按错误码处理。
- 撤销 token 后访问失败；Producer 不能调用 Admin apply。
- 输出跨语言 canonical/hash 测试向量，接收端始终自行计算 hash。

## 6. M3：生产应用与交互增强（另立实施评审）

保留需求：选定人工评估过的精确 Candidate，生产侧重新校验并由 Admin 授权应用。
需要明确部署/schema 兼容、备份/恢复、权限与审批依据后再排工程任务。
文件 hash 和 Preview Evaluation 不能直接充当生产审批身份。

后续必须覆盖：

- paper_key/source hash 在生产重新映射；
- 当前生产空白 Workspace 与人工历史检查；
- Candidate 不重新生成，严格绑定授权摘要；
- 生产应用 receipt 与科学写入事务及幂等；
- 备份和部署前核验，提交后恢复、部分批次报告；
- 已预填四篇仅核验或走 Reviewer 修订，成功预填替换另议；
- 只有人工反馈频率证明确有需要，再建设 Evaluation/Diff 专用 UI。

## 7. 评审时的重点

建议先评估 M1 是否能支持实际提取工作，而不是逐一批准远期 endpoint：

1. 输入包与 extraction guide 是否足以指导新 AI 进程完成一篇文章？
2. 每轮新 Preview、默认保留旧轮次是否符合人工比较习惯？
3. 现有 Reviewer UI + 结构化反馈是否足够首期使用？
4. Preview 专用 API 首期交付、独立 Producer API 第二期交付是否合适？

默认按设计 v2 执行这些选择；用户调整后同步修改两份文档，不允许只改工程文件。
