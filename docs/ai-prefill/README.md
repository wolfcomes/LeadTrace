# AI Prefill 文档入口

**新 Codex 对话先读 [START_HERE.md](START_HERE.md)。** 它定义当前流程、目录、职责、恢复方式和交接要求，不依赖此前聊天记录。

当前工作流版本：`deepseek-supervised-v2+self-check-v1-20260921`。这是实际输入包的recipe标签约定，组合v2指导、复跑经验和交付自检；不是Candidate/schema版本，也不改写旧任务的版本号。源阅读由DeepSeek执行，Codex监督及报告。

| 需要做什么 | 文件 |
|---|---|
| 新开/恢复任务、明确分工与阶段 | [启动入口](START_HERE.md) |
| 多harness监督、放行、反馈、成本口径 | [受监督运行指南](deepseek-supervised-runbook.md) |
| 结构、原图、Activity和Edge的提取要求 | [通用指南](extraction-guide.md) · [质量清单](deepseek-quality-checklist.md) |
| v2同文复跑发现的科学失误 | [复跑经验](deepseek-v2-rerun-lessons.md) |
| 交付前程序检查＋源自检 | [自检指南](deepseek-self-check-guide.md) · [自检模板](templates/deepseek-self-review.json) |
| 独立源审查、覆盖与准确性口径 | [审查协议](quality-audit-protocol.md) · [独立审查提示词](prompts/deepseek-audit.md) |
| 派发/修订 | [任务提示词](prompts/deepseek-task.md) · [修订提示词](prompts/deepseek-revision.md) |
| 跨对话交接 | [运行状态模板](templates/run-state.json) · [HANDOFF模板](templates/run-handoff.md) |
| CLI与Preview生命周期 | [CLI](../../leadtrace/ops/ai_prefill/README.md) · [Preview runbook](../../leadtrace/ops/runbooks/ai_prefill_preview.md) |
| 数据契约 | [Candidate schema](schemas/candidate-envelope-v1.json) · [Input schema](schemas/input-package-v1.json) · [质量记录模板](templates/deepseek-quality-record.json) |
| 清点与源自检契约 | [Compound inventory](schemas/compound-inventory-v1.json) · [Source self-review](schemas/source-self-review-v1.json) |
| 本次主线整合与测试 | [合并验收记录](verification-merge-2026-09-21.md) |
| 已知缺口、后续优化 | [维护与待办](MAINTENANCE.md) |

复制文档、填写任务prompt、记录实际文件hash后才算采用新指南。仓库CLI已实现验证、覆盖、自检、Preview与反馈工具；通用持久多harness调度器尚未实现，不能把指南当作后台运行服务。

`verification-*.md` 是按日期保留的验收历史。它们可能描述旧实例、旧工作区、旧规则或当时未实现的功能；不要照抄历史脚本目标或凭据路径。最近的交付前自检与三篇Preview刷新见 [2026-09-21验收](verification-self-check-2026-09-21.md)。旧首轮与升级指导的同文回归说明覆盖改善，尚不构成留出论文总体准确率或固定降本比例。

Schema快照与Python模型保持一致；`openapi-preview.json`是当前应用中六条AI assistance接口及其引用模型的摘录，不是全应用API，也不证明生产可用。更新模型后重新导出，不能修改历史运行包中的schema。
