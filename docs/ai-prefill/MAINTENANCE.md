# 维护边界与后续优化

本轮可用基础：隔离Preview生命周期与身份验证、候选契约/验证/覆盖/自检、workspace反馈导出、compound内活性与证据、可滚动目录、SAR/合成lineage分类、点线/分子结构切换及edge详情导航。部署主线后仍保留 `.worktrees/ai-prefill-tools`；不要自动移除其依赖与Preview进程所引用的路径。

## 已知能力边界

- 科学准确率仍需源审查；v2同文回归改善标签覆盖，不能证明全体结构/活动正确或固定成本下降。
- delivery self-check只验证已实现的确定规则及自检声明，未强制接入Preview API；用户明确授权可展示待修订草稿。
- 没有通用持久多harness调度器、任务租约/重启恢复服务或可靠token/费用账本。新对话依靠HANDOFF＋run-state＋实际process文件恢复。
- Candidate当前要求每个Compound有结构；结构未决不能用占位SMILES。身份及已知测量暂存unresolved sidecar，identity-only契约需要后续设计。
- 测量inventory/coverage和route-details等sidecar尚未统一成强类型可验证契约。逐tuple覆盖、正文/图中打印数值遗漏、ND与censored、SD/SEM源支持需要后续工具化。
- 检查一套代表骨架不足以确认全系列；新加入参考物、糖类立体中心、外围甲基和原图完整性仍是重点。
- 合成关系存在与温度/试剂条件正确分开检查，允许经route-local中间体的全局多步摘要；共享终产物不能凭编号连边。
- Native Preview是已验收路径；Compose Preview为未验收scaffold，不能当受限生产部署。
- 主应用生产迁移到0026/0027、生产部署、开启production AI apply需独立部署授权。合并源码不执行它们。

## 优先优化顺序

1. 固定新论文样本做“自检前/后”对照，保留独立审查，记录修复与新引入错误、耗时及实际费用。
2. 统一measurement tuple和审核slot sidecar；用程序查遗漏、重复、状态汇总与ref/hash一致性，未知分母明确null。
3. identity-only身份与测量保留方案；不让结构未解决导致compound/活性一起消失。
4. 稳定输入打包与分阶段runner：实际guide hash、限时落盘、身份验证、失败恢复。开始前优先沿用当前工具，不盲目重放旧实验脚本。
5. 新数据质量得到验证后再考虑扩大并发和自动化程度。

## Git与本机运行状态

Git保存代码、迁移、测试、指南、模板、schema、去凭据的验收摘要。`leadtrace-data/`保存论文运行、候选、图像、数据库、实例descriptor与凭据；该目录被忽略，不提交。仓库中的历史绝对路径仅作证据，当前实例由运行HANDOFF明确指定。

主分支合并后继续优化时：先确认main和保留分支的状态，从main整合最新修复后再改；保持任务范围内提交。保留工作树不是保证两个分支永远同步，不能在另一个会话静默覆盖进行中的工作。
