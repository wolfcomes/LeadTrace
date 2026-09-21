# Preview 身份接线验收（2026-09-20）

> 历史阶段性记录。当前实现、实际 UI 迭代与清理验收以 [最终验收记录](verification-2026-09-20.md) 为准。

本轮完成 T5/T6 的运行时身份接线。M1 整体仍在实施；完整 Preview 生命周期和真实 UI 验收不在本轮完成声明内。

后续进度：native 创建／进程管理已继续实现，最新范围和证据见 [创建与进程验收](verification-preview-provision-2026-09-20.md)。本文保留身份接线批次的历史测试记录。

## 实现

- 新增 `Settings.preview_registry_path`。Preview 启动需要显式 registry、实例 UUID、baseline、PostgreSQL endpoint、`_preview` 库名和三类目录。
- `bootstrap_database()` 在连接前读取 registry；连接后验证实际数据库。Web lifespan 也验证注入的数据库资源，不允许空资源启动。
- 每个 Preview HTTP 请求首先检查身份，并在 Session 开启每个外层事务时再次检查，包括登录等认证写入。异常返回 `503 PREVIEW_IDENTITY_MISMATCH`，不泄露 registry 内容或凭据。
- `PreviewApplicationService` 必须接收 Settings；即使不经过 HTTP，apply 也在自身连接上复核并锁定 marker，再处理 receipt/科学记录。
- 同时匹配 registry/Settings/实际连接的 database、host、port，恰好一个 marker、instance、baseline，以及恰好一个当前 Alembic head。
- source/assets/artifacts 路径必须一致、存在且互不包含；registry 必须位于它们之外；所有路径拒绝 symlink。v1 只接受已登记的 `source_pdfs` source root。
- registry 必须为不超过 64 KiB 的普通 JSON 文件，状态为 ready。缺失、格式错误、initializing、archived 均不会启动/继续服务。
- 路由注册不再创建 artifact 目录。身份校验不补建目录，不自动创建 marker，不认领已有数据库。
- `PreviewRuntime.create()` 记录 artifact_root；Compose 只读挂载 registry 并显式设置路径。

## 测试方式与证据

新建 PostgreSQL 16 cluster：`/tmp/leadtrace-prefill-identity.fPfSAH/`，仅使用私有 Unix socket，没有 TCP listener。运行前确认实际库名、用户和 data_directory。

普通数据库回归使用本 cluster 的 `ai_prefill_test`。Preview 测试 fixture 从显式测试连接创建随机 UUID 命名的独立 `_preview` 数据库，迁移、准备 marker/registry/目录，测试后只删除自己创建的数据库。没有放宽 `_preview` 规则，也没有将通用 `DROP SCHEMA public` fixture 用于 Preview 数据库。

已完成失败复现再修复：

- 错误 host/port/source root/实际 DB 未被旧 helper 拦截。
- 缺失 marker、baseline 漂移、initializing registry 仍能通过旧启动流程。
- 启动后 registry 改变仍允许请求进入原有认证流程。
- Preview bootstrap 返回空资源仍能启动。
- 运行中新增 Alembic revision 行，旧检查只看第一行。

独立代码审阅之后，额外验证了启动后删除 marker、无登录尝试写入，以及三类目录缺失时拒绝启动且不重新创建。

最终完整回归：`221 passed in 262.70s`。在 `leadtrace/backend` 下显式设置本轮独立测试 URL 后执行：

```bash
../../.venv/bin/python -m pytest \
  tests/ai_prefill \
  tests/ops/test_ai_prefill_cli.py \
  tests/ops/test_ai_prefill_cli_smoke.py \
  tests/ops/test_ai_prefill_preview_cleanup.py \
  tests/ops/test_ai_prefill_preview_runtime.py \
  tests/security/test_route_permission_matrix.py \
  tests/db tests/workspaces/test_assignment.py \
  tests/ops/test_prefill_four_production_examples.py -q
```

身份专项：`43 passed in 63.33s`，覆盖 startup/guard/identity/direct apply/HTTP 全流程。专项与完整回归有重叠，不能相加统计。

CLI offline doctor、compileall、带 example env 的 Compose config、`git diff --check` 均通过。最终查询确认本轮创建的临时 `_preview` 数据库剩余数为 0；随后已停止整个临时 PostgreSQL cluster，保留上述目录中的日志。

## 部署影响和剩余工作

现有 registry 需要包含 artifact_root、commit、lockfile_sha256 等字段并与运行时路径一致；旧的不完整实例将明确拒绝启动。Compose 的 registry path 使用容器内命名空间，配置方式见 [runbook](../../leadtrace/ops/runbooks/ai_prefill_preview.md)。

本轮没有部署真实站点，也没有执行 production apply/migration。完整 create/start/stop 编排、独立 provisioning/runtime role、20 篇 catalog 和账号初始化、host/container 资源映射、真实 PDF 字节与裁剪接入、Workspace 自动导出、数据库/进程清理、浏览器 v1→反馈→v2 迭代仍需继续。

扩展数据库回归时发现两处旧测试硬编码 `0025_ai_prefill_runs` 为 head。
已改为从 `ScriptDirectory` 读取当前 head，并继续验证实际 DB revision、科学表索引和
`head → 0020 → head` 的结构图 occurrence 约束往返。没有修改历史 migration 来迁就测试。
