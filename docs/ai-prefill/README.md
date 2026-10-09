# AI Prefill 文档入口

先读 [START_HERE](START_HERE.md)，选择从头预填或已有候选自检/修补。流程 `model-neutral-v4-20261008`：routine 由所选模型连续完成生产和自检；evaluation 由 Codex 监督测试与改进指南。科学独立审查始终使用新会话中的审查模型上下文，生产者不持有 Preview 凭据。

| 需要做什么 | 当前文件 |
|---|---|
| 选择预填/修补/复核与模式、恢复状态、CLI 任务 | [START_HERE](START_HERE.md) · [运行指南](model-runbook.md) |
| 科学提取规则：Compound、结构、测量、关系、lineage | [提取指南](extraction-guide.md) |
| 生产者自检、已有候选增量修补 | [自检指南](self-check-guide.md) · [自检模板](templates/self-review.json) |
| 独立审查/抽样/继承/统计 | [审查协议](quality-audit-protocol.md) |
| 简短交付检查、按风险查阅 | [质量清单](quality-checklist.md) · [常见问题](quality-pitfalls.md) |
| 实际派发提示词 | [预填](prompts/producer.md) · [修补](prompts/repair.md) · [独立审查](prompts/review.md) |
| 持久运行状态/交接/费用 | [run-state](templates/run-state.json) · [HANDOFF](templates/run-handoff.md) · [质量记录](templates/quality-record.json) |
| CLI 与受信 Preview 操作 | [CLI](../../leadtrace/ops/ai_prefill/README.md) · [Preview runbook](../../leadtrace/ops/runbooks/ai_prefill_preview.md) |
| 契约 | [Candidate](schemas/candidate-envelope-v1.json) · [Input](schemas/input-package-v1.json) · [Compound inventory](schemas/compound-inventory-v1.json) · [Source self-review](schemas/source-self-review-v1.json) |
| 能力边界/网页交互方案 | [MAINTENANCE](MAINTENANCE.md) |
| 历史源码整合证据 | [验收记录](verification-merge-2026-09-21.md) |

当前指南按职责维护，每条科学规则有权威出处；完整 bundle 冻结真实文件/hash，模型按角色只读必要内容。历史运行不改写，新 workflow 标识不是数据 schema 升级。session 元数据与结构化 handoff 支持续作追踪；当前 dsh headless 没有原生 resume，task run 不是自动独立审查/应用调度器，网页 Admin 队列支持一次独立复核同时生成修补方案，再由 Admin 接受保存的修改；自由对话 broker 尚未实现。

Git 保存指南、代码、契约、模板和回归测试；源论文、候选、图片、数据库/凭据、运行/评测记录放忽略的 `leadtrace-data/`。已完成旧阶段文档可在 Git 历史和本机 `leadtrace-data/ai-prefill-docs-archive-20260921/` 追溯，不作为当前默认阅读材料。数据库迁移链和兼容 schema 必须保留。`openapi-preview.json` 只是 AI assistance 接口摘录，不证明生产部署已启用。
