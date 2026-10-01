# 能力边界、受限交互与后续优化

当前流程 `deepseek-led-v3-20260923`。保留 `.worktrees/ai-prefill-tools` 及其 Preview/依赖；合并后不自动删除。运行事实留在实际 HANDOFF，本文只记录可复用边界和优先级。

## 已实现与尚未实现

- 现有候选契约/validate/coverage/self-check、workspace 反馈导出和隔离 Preview 生命周期继续使用。source self-check 是确定性规则＋声明检查，不是源科学验证，也未强制接入所有 Preview API。
- `task prefill` / `task selfcheck` 建立真实冻结包；`task run` 是一次有界 headless 生产调用，保存状态并按 paper_key 保持单写者；`task status` 返回保存的 checkpoint 与 leader_identity_matches，并非完整实时状态。`task recover` 在原锁与进程身份核验后将已无活进程的 running 标记 interrupted，不终止或重跑任务。续修建新 job，不覆盖旧包。默认本机锁根 `~/.local/state/leadtrace/ai-prefill/locks`，全部操作者须共享该根或统一 `LEADTRACE_PREFILL_LOCK_ROOT`；不同根不互斥，不是分布式锁或沙箱。它不是自动独立审查编排、后台持久队列或应用授权器。
- `session inspect` 提取实际会话身份与可获得 usage 元数据；显式 dsh-home 对应实际子进程环境的 DSH_HOME，不固定假设用户默认目录。已安装 headless CLI 没有原生 resume；内部 Agent API/nativeWeb 的续接能力不等于当前 CLI 可调用。当前采用结构化 handoff 新会话，不声称保留模型上下文或命中缓存。
- 墙钟 timeout 已有执行边界；token/金额预算和最大修订轮数不是硬执行配额。审查继承的内容/依赖 hash 与统计校验仍需操作者核验，不把文档约定当自动实现。
- Candidate 要求每个 Compound 有结构；未决完整身份与测量留 sidecar，不能造占位 SMILES。measurement tuple、route-details 等尚未统一为强契约；全篇测量 coverage、源语义和自检真实性仍需 DeepSeek 检查。
- self-check 已报告 Lineage 分量/孤点/环/合成角色冲突/逐类型未参与，作为 review 诊断，不自动拆组或加边；其科学含义/非参与原因/优选依据没有自动验证，没有独立优选字段或 target/baseline/isolated 枚举。生成图显示、逐组加载和反复切换稳定性分别验证；布局拥挤不授权删科学边。
- Native Preview 是已有验收路径，Compose 仍有未验收范围。科学数据留在各自环境；合并源码不授权生产迁移、部署或启用生产 apply。

## 网页 reviewer 交互：采用受限任务 broker

选用 LeadTrace 后端控制的任务 broker，不把 harness/nativeWeb/shell 端口直接暴露给 reviewer。先把当前离线任务和元数据运行稳定；本轮不实现网页聊天或开放端口。后续可复用当前 task/session/handoff 工件，按以下边界建设：

| 维度 | 必须具备的行为 |
|---|---|
| 身份与范围 | 现有登录/Reviewer 权限，绑定 paper/workspace/source/版本；只能访问被授权工作区与任务 |
| 操作 | 白名单的提问、解释记录、请求自检、提出有限修补；不允许任意命令、路径、工具或系统提示词注入 |
| 上下文 | 显示结构化结论、定位与允许的材料；不返回模型 reasoning logs、home 配置、凭据、其他论文会话 |
| 生产与审查 | 生产会话可讨论/修补，独立审核另建上下文；明确区分解释、自检、独立审查与人工批准 |
| 成本与并发 | 每任务/用户限输入长度、预算/超时/轮数、速率与并发；paper/source 单写者，取消与恢复可追踪 |
| 写入 | AI 先产生候选差异和证据，reviewer 查看并确认具体差异，后端版本检查后应用；没有隐式数据库写工具 |
| 人工编辑 | 基于最新版本生成修补；提交遇版本冲突重新对齐，不覆盖人类修改或重置 workspace |
| 留痕与输出 | 请求/回复/变更/源与版本 hash/实际费用有可审计记录，输出过滤敏感内容；不把模型状态字符串当批准 |

网页里的“继续原任务”优先复用可验证的生产会话；原生续接不可用/上下文失效就透明地用结构化 handoff 新建。不能通过 reviewer 提问把独立审查上下文重新当生产会话且仍称独立。接入前必须测试越权 paper/workspace、提示词注入、预算/取消、并发与版本冲突、敏感输出和人工确认流程。

## 优先级与验证方式

1. 用固定新论文验证 routine 相比 evaluation 的成本：同源/同范围/同独立审查标准，记录准确性、覆盖、修复/新引入错误、返工、DeepSeek＋Codex 实际费用与墙钟时间。无 usage 则 null，不能从耗时换算账单。
2. 完善 measurement tuple/审核记录及依赖失效检测，把低成本确定性检查前移；完整 Compound coverage、图语义和正确性分别评价。
3. 在真实 harness 能力和稳定运行恢复充分验证后，补持久任务队列、预算执行和受限网页 broker；不要先开放聊天端口再补控制。
4. 设计 identity-only 身份/测量保留方案；独立契约和迁移，避免未解析结构导致已有观察消失。

## 文档、Git 与发布

各指南仅保留当前有效规则，历史实验案例不成为每阶段必读。完整 bundle 冻结不改写，活状态放 ignored runtime；已完成实验/过期计划整合有效经验后归档并验证 hash，Git 历史保留。兼容 schema、迁移和回归测试不按文档精简规则删除。其他任务未完成计划不随本轮清理。

Git 只保存可移植代码/指南/模板/契约，`leadtrace-data/` 保存源、候选、图片、数据库/凭据与运行记录。保留 worktree 不保证与 main 永久同步；整合前核对双方修改，保存 main 的 auth、Ketcher、CSP 修复。

源码合并不切生产服务。发布需要实际授权、选定提交、前后端一致构建、目标 schema 核对、验收与回退方案。**Preview 科学记录、候选、图片、数据库不迁入生产**；生产保留自己的记录。0027 等 schema 迁移不授权把 Preview 分类/数据套到生产。实际部署路径与实例以最新 runbook/交接核验，不复用过期本机诊断。
