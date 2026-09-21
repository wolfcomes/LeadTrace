# AI_prefill主线整合验收（2026-09-21）

目标：将受监督AI_prefill、Preview、审核UI及自检工具整合到本机main，保留开发工作树与现有Preview，并使新Codex对话不依赖聊天历史即可接手。

## 整理内容

- 根AGENTS指向START_HERE；明确Codex监督/DeepSeek读源、指南实际拷贝/hash、输入身份、分阶段放行、恢复/并发边界、Preview与交接。
- README提供当前文档地图，MAINTENANCE区分当前能力与待办；新增HANDOFF/run-state模板。正式InputPackage的target/source_locator与历史实验自定义source明确分开。
- 本机三篇运行生成实际HANDOFF/run-state，复核冻结候选hash。旧Preview交接原样归档，当前入口只索引最新状态，避免过期计数和脚本误用。
- 补齐Candidate的lineage_type schema，导出CompoundInventory/SourceSelfReview schema，更新六条assistance接口的OpenAPI摘录；模型一致性及所有引用解析验证通过。
- 评审发现并修复两个边界：实体ref不能包含receipt路径分隔符 `/`；candidate export使用原子不覆盖发布，拒绝父文件/已有目标/符号链接。

## 集成和状态

功能提交fd83eb6；cd2060c将原main 124c5ed整合到功能分支。前端package脚本冲突保留Preview E2E和Ketcher CSP两者。主线登录会话、Ketcher、CSP修复已复核保留。

保留 `.worktrees/ai-prefill-tools`、`codex/ai-prefill-tools`、安装依赖、Preview进程与数据。Git只保存源码/文档/测试/schema；源PDF、运行结果、凭据和数据库仍在忽略目录中。根目录两份未跟踪four-production-example计划文件不纳入本次提交。

这是本地源码集成，未推送远端，也未执行生产迁移或部署。生产0026/0027迁移与部署仍需独立任务。现有Native Preview继续作为已验证路径；Compose仅scaffold。

## 验证

后端全套964项执行完成：首次944 passed、19 failed、1 skipped（1051.25s）。19项失败均定位到测试辅助代码/旧版本假设：catalog使用rsplit误解析Unix socket数据库URL（14项）；upgrade head后仍预期0026（1项）；preflight fixture固定0025而实际库已升级head（4项）。修复为SQLAlchemy make_url解析和实际迁移head；生产数据库身份/迁移校验未改。另补齐原本只删除trigger却无断言的测试。

修复后三个受影响文件完整串行重跑：**71 passed（71.76s）**，覆盖全部19项失败，无剩余失败。全套与定向补跑合计确认963个独立用例通过；没有声称修改后重新跑了完整964项。唯一跳过的是需要 `LEADTRACE_TEST_REDIS_URL` 的真实Redis/Celery broker用例，本机没有为此次验收配置该服务。

```bash
# 均在 leadtrace/backend；显式使用独立测试数据库环境变量
../../.venv/bin/python -m pytest -q
../../.venv/bin/python -m pytest tests/catalog/test_import.py tests/db/test_migrations.py tests/ops/test_paper_centric_preflight.py -q
```

- 前端29个文件、198项测试通过；typecheck及生产构建通过。构建保留现有chunk-size和上游use-client警告。
- 真实Ketcher CSP Chromium测试1项通过（实际SMILES导入/Molfile导出）。
- 现有Preview只读Chromium测试1项通过：009登录、PDF身份/加载、RDKit、SAR/合成导航和edge详情。未设置PREVIEW_LIVE_EDIT；Codex未查看生成的论文截图。
- 独立代码复核：两处P2修复通过，无新增合并阻断；25项离线回归通过。二次复核确认三个测试修复未弱化校验，schema/OpenAPI一致。
- Markdown相对链接检查0失效；git diff --check通过。

本机详细日志位于 `leadtrace-data/ai-prefill-merge-20260921/`。数据库回归使用独立临时PostgreSQL与prefill_merge_test，串行运行；未用live Preview或生产数据库。

## 科学与自动化边界

三篇已有候选仍是draft/needs_revision；本轮未重新提取或修正科学数据，不把代码合并或自检通过等同科学批准。当前自检可检出已知dose/单位/coverage/hash/ref问题；没有执行新的DeepSeek自检前后对照实验。通用持久多harness调度器、完整测量tuple coverage、可靠费用账本及identity-only候选仍是后续优化。


## 合并后整理与正式网站诊断

用户进一步要求main保留现行指导、Preview数据不进入正式库。已将22份阶段性报告和已完成计划完整归档到忽略目录 `leadtrace-data/ai-prefill-docs-archive-20260921/`，逐文件hash验证后移出当前源码树，历史仍可从2f27cc8追溯。有效质量规则保留在quality-pitfalls.md；新任务入口、运行指南和引用已更新，相关Markdown链接无失效。迁移链、契约版本和回归测试保留。本次仅文档整理，git diff --check通过，无应用代码变更。

只读检查正式Caddy配置和进程cwd，确认正式前端仍从124c5ed release服务，HTTP返回HTML与该文件逐字节一致；API/worker仍使用leadtrace-cutover-5ea。源码合并并未发布正式网站。未重启正式服务、切换路由、操作正式数据库或将Preview数据迁入正式库。
