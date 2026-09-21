# Preview 创建与进程管理验收（2026-09-20）

> 历史阶段性记录。当前实现、实际 UI 迭代与清理验收以 [最终验收记录](verification-2026-09-20.md) 为准。

本轮完成 T6 的 native 后端创建／运行流程。M1 仍在实施；没有将本机 API 后端称为完整前端站点或科学人工验收。

## 实现范围

- CLI 新增 `preview create/start/status/stop`。核心服务位于已安装的 `app.ai_prefill` 包，ops 保持薄入口；旧 `PreviewRuntime` 导入路径通过 re-export 兼容。
- create 要求显式的受保护 provisioning JSON，目标库名以 `_preview_admin` 结尾；不读取默认应用 DB URL。独立 cluster 是操作前提，名称后缀不能证明与生产隔离。
- 预检恰好 20 篇 catalog manifest 和 PDF；先制作专属副本并核对内容，再创建持久资源。snapshot 文件权限 `0444`；native 模式没有容器只读挂载，也不隔离操作系统所有者。
- 实例目录、UUID 派生数据库或 runtime role 已存在均拒绝，不认领旧资源。新目录权限 `0700`。失败保留 `initializing` 和最后进入的 phase，不自动删除数据库。
- provisioning role 执行 migration 并拥有数据库／schema。catalog、Admin、Reviewer 及 marker 在同一事务提交。
- runtime role 随机独立密码，禁止超级用户、建库、建角色、复制及 bypass-RLS；无 schema CREATE，identity／Alembic 不授予内容修改权限。marker 和 receipt 的 `UPDATE(id)` 仅用于满足 PostgreSQL 行锁权限，receipt 另有 INSERT。
- Web profile 不含 provisioning DSN；session secret 和账号密码分别随机生成。`runtime.json` 与 `credentials.json` 均为当前用户的 `0600` 普通文件，CLI 只输出路径和用户名。Settings 来源固定，不合并继承环境或 `.env`。
- 使用受限 runtime 连接核验完整身份后才发布 ready registry。验证期间公共 registry 一直是 initializing。
- native origin 仅接受 `http://127.0.0.1:<显式端口>`。start 先占用监听 socket、核对 DB 身份和 pidfd 支持，再传递 FD 给 Uvicorn 子进程，等待真实 `/health/ready`。
- start/status/stop 使用 flock；通过 PID、`/proc` 启动时间和完整命令/profile 确认归属。stop 用 pidfd，拒绝未知进程；当前 Python 缺少包装函数时使用 libc pidfd。启动异常通过刚创建子进程的独立 pidfd 清理并回收，不依赖尚未建立的进程记录。
- status 的 running 只表示进程存活与归属核对；不会额外宣称实时健康。后端 stdout/stderr 当前丢弃，避免底层异常泄露 DSN；诊断细节因此有限。
- 新 native 实例明确拒绝旧 filesystem-only archive/destroy；plan 可查看。完整数据库／角色／反馈归档清理未实现，不能以只删资产目录假装实例清理成功。

## 测试与审阅

本轮使用全新 PostgreSQL 16 cluster：`/tmp/leadtrace-prefill-provision.YcSQKk/`。仅私有 Unix socket、无 TCP；运行前核对 current_database、current_user、data_directory。管理员连接只对测试创建者使用本地 trust，runtime 连接使用 SCRAM-SHA-256。

普通回归连接本 cluster 的 `ai_prefill_test`；provisioning 测试再创建 UUID 独立的 `_preview_admin`，通过实际创建流程建立 `_preview` 和受限 role，测试后只删除本测试拥有的库与角色。没有连接生产数据库。

真实集成覆盖：

- 从空库升级到 head，导入 20 篇／20 个 Source、两名账号。
- 受限 runtime login、health 和 Admin 源 PDF GET，返回 PDF SHA-256 与 catalog 一致。
- 受限 runtime 完成科学 apply、receipt INSERT 和行锁；同 key 重放不产生第二张 receipt。
- 建表、建库、改 baseline、删 marker、改 Alembic 均返回权限不足；建库在 AUTOCOMMIT 下测试，明确检查 SQLSTATE 42501，排除“事务中不允许建库”的假阳性。
- 真实 CLI create → start → health → status → stop；进程重复 start/stop、原端口立即重启和跨 cwd status。
- 错误 catalog 不创建实例资源，seed 故障回滚 catalog/marker 并保持 initializing。
- profile 权限、symlink/体积/环境来源、无显式 profile、秘密不出现在 CLI 输出、外来 PID／端口冲突拒绝。
- 启动后读取 starttime 返回 None、抛异常、获取子进程 pidfd 失败时，真实子进程退出、回收、移除记录并释放端口。

按 TDD 先复现缺失创建入口与行为，再实现；独立只读审阅发现并修复 `localhost` IPv4/IPv6 歧义和 starttime 读取失败可能留下子进程的问题。额外回归发现 Pydantic 会合并继承环境中的嵌套 source_roots，已改成仅初始化参数来源。修复后审阅未发现本轮范围内剩余阻断问题。

本轮完整回归：**256 passed in 292.51s (0:04:52)**，无失败或跳过。命令在 `leadtrace/backend` 下执行，并显式设置上述临时 cluster 的 `LEADTRACE_TEST_DATABASE_URL`：

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

CLI doctor／preview help、compileall、`git diff --check` 及 AI Prefill Python/Markdown 空白检查通过。退出前核对 UUID 实例数据库剩余数为 0、runtime role 剩余数为 0，系统中无 native Preview backend 子进程；随后停止本轮临时 PostgreSQL cluster，保留其日志／数据目录供诊断。

## 尚未完成

- T6 的单一前端/API origin、明显 Preview 标记、容器只读 source mount、真实浏览器站点验收。
- Compose provisioning／runtime 凭据拆分；当前 Compose 仍共用数据库 owner，不属于本轮验证的受限部署。
- T7 apply 的实际 PDF 字节固定／复核、裁剪服务接线及剩余 Workspace 版本／并发边界。
- T9 数据库 Workspace → Candidate 自动导出。
- T10 完整 receipt／快照／人工编辑／反馈归档及精确数据库／角色删除。
- T11 v1 → 人工反馈 → v2 → diff → 再评估及跨进程冷启动人工验收。

运行步骤见 [Preview runbook](../../leadtrace/ops/runbooks/ai_prefill_preview.md)。后端尚无仓库内 lockfile；runbook 使用本地 `pip freeze` 依赖快照摘要，不能把它误称为已经实现严格锁定的安装流程。代码 revision 与摘要也不能标识工作区的未提交修改。本轮保留所有现有改动，未提交、未部署生产、未执行生产迁移或 apply。
