# AI Prefill M1 验收记录（2026-09-20，最终本机迭代）

> 本记录为原始 M1 迭代。用户后续反馈后已补入 376 条 Activity 与 68 个原文截图定位，并放宽 Edge Evidence 门槛；当前查看结果以 [补完整性验收](verification-enrichment-2026-09-20.md) 为准。

状态：M1 本机实现与真实 Preview 技术迭代已完成；用户尚未进行最终科学内容审核。本文替代此前仅有后端集成测试的阶段性状态。M2 独立 Producer 与 M3 生产应用未实施。

## 查看入口与运行资料

- Worktree：`/data/home/zhangzhiyong/lead_optimization_collection/.worktrees/ai-prefill-tools`。
- 分支：`codex/ai-prefill-tools`；所有改动保留未提交。
- 最终页面：<http://10.21.53.251:18080/review/tasks>。用户要求局域网直连后，新增绑定此内网 IP 的 TCP 转发入口，并更新该实例 allowed_hosts；原 loopback 入口继续可用。局域网入口的运行/恢复资料见外部 HANDOFF。
- 登录账号：`preview-reviewer`；操作员 API 账号：`preview-admin`。
- 实例：`62858923-98c5-45f0-acbe-abc27058fb0a`。
- 外部实验目录：`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/ai-prefill-preview-20260920.C191Fl`。
- 密码仅保存在上述目录 `instances/62858923-98c5-45f0-acbe-abc27058fb0a/credentials.json`（0600），不复制到文档。
- 同目录 `HANDOFF.md` 提供精确的启动、状态、浏览器验收、恢复命令及证据位置。
- 最终后端与独立 PostgreSQL cluster 保留运行，供用户查看；测试用临时 cluster 已停止；普通首页 `/papers` 展示已发布内容，应从 `/review/tasks` 进入预填 Workspace。

## 四篇真实结果

来源为既有本地 PDF/历史提取 CSV，通过只读适配器生成候选。只读取四篇历史脚本中的映射和纯转换函数，没有运行其生产 prepare/apply/main。

| Paper | Compound / Structure | Lineage | Edge | Evidence / link | Activity | PDF 结构定位 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| LT-JMC-2024-67-05-004 | 11 / 11 | 1 | 6 | 6 / 6 | 0 | 0 |
| LT-JMC-2024-67-05-005 | 41 / 41 | 5 | 35 | 35 / 35 | 0 | 0 |
| LT-JMC-2024-67-05-010 | 6 / 6 | 1 | 5 | 5 / 5 | 0 | 0 |
| LT-JMC-2024-67-05-013 | 10 / 10 | 1 | 8 | 8 / 8 | 0 | 0 |
| 合计 | 68 / 68 | 8 | 54 | 54 / 54 | 0 | 0 |

四篇应用均提交成功，receipt verify 均为 `committed`；失败和未开始列表为空。最终 Workspace 均为 version 2。对应凭据和 Reviewer 直达链接保存在 `v2-applications.json` / `final-verification.json`。

所有候选允许预览但保留 `needs_review`；没有把成功解析/结构绘图等同于科学正确。六个科学审核 section 均待人工确认。Activity 与原文结构裁剪定位尚未从历史数据中提取，Candidate omissions 明确记录缺口；RDKit 仍有部分未定义立体化学提示。未进行 Admin 批准或发布。

## 已完成的实际迭代

1. 本机独立 cluster 创建两个正式验收实例，每个导入固定 20-PDF catalog，随机创建独立 Admin/Reviewer、受限 runtime role、marker、资产/实验目录。没有使用生产数据库或生产资产目录。
2. 第一轮四篇真实 apply 生成 68 张 RDKit PNG。真实浏览器登录、核验 PDF 哈希并等待 PDF.js 渲染、解码结构 PNG、查看谱系图和 Evidence。修复初轮缺结构绘图服务及 Preview 横幅滚动重叠问题。
3. 通过真实 Reviewer UI 在 004 的 compound `10g` description 追加明确标识的自动化验证备注，刷新后保留；Workspace 从 version 2 变为 3。其他科学字段与审核状态未修改。
4. CLI `evaluation record` 绑定候选/payload/source hash、report、receipt、真实/初始 Workspace 版本和完整快照。decision 为 `needs_revision`，reviewer 明确为自动化检查，六项 coverage 为 `not_reviewed`，没有伪造人工审核。
5. CLI `candidate export-workspace` 从实际 version 3 科学记录导出 child Candidate `LT-JMC-2024-67-05-004:v2`，保存实体引用与审核元数据。diff 确认只改变 compound `10g` description。
6. 创建新 UUID/数据库的最终实例，应用 004 child 与其他三篇原候选。全部成功，保留父候选/反馈/快照，不继承原 Workspace 的审批状态。
7. 最终只读 Playwright 验证页面；额外对四篇全部 PDF 和 68 张 PNG 核验。004 备注在新数据库 API 与实际页面编辑框中一致，没有再次保存。四篇最终评估仍为 `needs_revision`。
8. 对最初缺绘图的旧实例做完整归档：同一数据库快照上的 custom `pg_dump`、行/schema、PDF、资产、工件与哈希清单。恢复到另一个临时数据库，验证 20 Paper、68 Compound/Structure、8 Lineage、54 Edge/Evidence、4 receipt。随后删除该旧实例的 DB/role/source/asset 副本，工件和归档仍可读，最终实例保持工作。

这是自动化辅助的技术反馈演示。计划中的最终人工科学反馈由用户接下来在实际页面完成，尚不能宣称已得到人工 acceptance。

## 实现收尾与边界验证

- Apply 固定实际 PDF 字节、复核 SHA/size/pages 并严格解析，裁剪使用相同字节；绘图与裁剪新资产跟随外层事务失败或 Session.close 回滚。幂等 replay 可以在源文件随后不可读时返回已提交 receipt。
- Existing Workspace/run 必须携带预期版本并纳入 request digest；隐式重复 assignment 返回业务冲突。
- Preview 专用写 API 按实际流字节限制 2 MiB，5000 科学对象包括每个 Compound/Structure、Lineage member/edge；伪造 Content-Length 不能绕过。生产不注册这些路由/中间件。apply/receipt 返回真实 Reviewer URL。
- Workspace export 支持稳定旧引用、新增人工实体、精确 Decimal、重复 assay；无法用 Candidate v1 表示的字段、丢失实体和冲突版本明确拒绝。
- CLI 在写工件前检查输出冲突，排他原子发布输出；中断后以同 ID 重试会核对全部绑定内容并复用原时间戳。不会留下只能靠覆盖修复的不可变工件。
- Native archive/destroy 验证完整文件/数据库状态、marker、数据库/角色 OID；未知资源、symlink、后续编辑、归档损坏被拒绝。中断的 DB drop 和部分目录删除可恢复。未覆盖的 large objects/materialized/foreign tables 明确拒绝。
- 独立 JSON schemas 与真正的 OpenAPI 3.1 文档已重新生成，包含 Evaluation 完整绑定和 API 限制。

## 验证证据

最终后端回归：**429 passed, 1 skipped in 597.18s**，退出码 0，完整输出保存在同实验目录 `final-backend-tests.log`。唯一跳过为既有真实 Redis/Celery broker 测试：本环境未提供 `LEADTRACE_TEST_REDIS_URL`；本机 Preview 不启用 Celery/beat。执行范围包括完整 `tests/ai_prefill`、CLI/lifecycle、权限矩阵、全部 migration/db、Workspace assignment、历史四篇兼容，以及受此次绘图/裁剪事务修改影响的 jobs/chemistry/structure API。

已完成专项结果：

- 前端 90 项测试、typecheck、生产 build 通过。
- 真 PostgreSQL 的 native process/static 前端 34 项通过，包含不同 loopback host、端口占用拒绝和立即重启。
- 四篇 v1 UI 编辑 E2E 通过（7.8s）；布局修复后只读 E2E 通过（7.0s）。
- 最终 v2 真后端 E2E 通过（7.1s）；四篇 PDF hash 一致，68 张 PNG 均有效。
- CLI 真实 DB 的反馈/export/重试/篡改拒绝专项 19 项通过。
- Native cleanup 13 项通过，另增加真实 pg_restore roundtrip 验证通过。
- 新 shell (`env -i`, `bash --noprofile --norc`) 仅凭实例文件运行 status，health/login/environment 均为 HTTP 200。
- 无历史对话的独立代理仅凭 HANDOFF 完成最终实例 stop/start、两账号登录、四篇 receipt/candidate/Workspace/feedback 恢复、diff 一致性及只读浏览器检查（1 passed，7.2s）。重启后四篇 Workspace 仍为 version 2。证据：`cold-start-independent.json` 与 `browser-fresh-session/`。

专项测试与最终回归存在重叠，不能相加。测试数量不代表科学审核范围。

## 交付限制

- Native 是本轮验收通过的运行方式。Compose 仍为未验收 scaffold，存在共享 owner 凭据等差异，不能按正式部署使用。
- Native PDF 副本为 0444；这是文件权限限制，不是容器只读挂载，也不隔离拥有这些文件的 OS 用户。
- 后端没有仓库内锁文件；本轮保存实际 pip freeze 及哈希。Git revision 不覆盖未提交代码，另保存变更文件哈希供交接核对。
- 运行期实例只使用受限 DB role，初始化账户使用独立 cluster 中的 provisioning profile；密码/会话秘密均保留在受保护文件。
- 本轮未提交、未合并、未部署生产迁移，也没有重跑四篇 production apply。M2/M3 需另行立项。
