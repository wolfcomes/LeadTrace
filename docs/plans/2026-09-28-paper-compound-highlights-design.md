# 文章级起点与优选化合物标注建议

状态：2026-09-28 已实施方案 1，通过验证并更新现有 Preview（0030_compound_highlights）；不自动回填论文事实。

## 语义与界面

建议增加与 Lineage Member role 正交的文章级标注，关联本篇已有 Compound：

- **研究起点 / Study starting point**：作者以其为基础开展本篇优化的 hit、lead 或已知先导。不是每条合成路线的起始试剂，也不因图上没有入边就自动成立。
- **论文优选 / Paper-prioritized compound**：作者综合活性、选择性、PK、体内效果、安全性等，明确选择或优先推进的分子。不是所有 terminal，不等于单项最强活性，也不使用易与生物靶点混淆的 target 标签。

每类允许多个分子；同一分子可同时承担两种身份。多系列论文记录适用系列/研究范围，不能强行选出唯一全篇起点或终点。还没有核对、未找到明确陈述与作者明确未选择应区别说明；不能用空列表自动断言论文没有优选。

文章信息区显示两组结构卡，Compound 列表和 Lineage 节点显示简短徽标。点击徽标可查看作者选择理由和来源。仍保留 root/intermediate/terminal，表示局部关系角色。

## 记录与审核

建议使用独立的 paper/workspace-scoped annotation，每条关联 compound_id、role、scope、理由、来源 Evidence、review_hint 和审核状态。来源 Evidence 使用当前的物理 PDF 页码、原文摘录/区域，不以图拓扑替代。需要唯一性和同篇外键约束、乐观版本校验、修改历史、快照/发布冻结、候选契约及人工编辑贯通。

主方案只标注源文支持的身份，未确定者列为待核事项而不显示确定徽标。若后续允许 AI 建议身份，必须标明未审核，不能与 reviewer-confirmed 混同。

自动预填时 DeepSeek 先独立核对 Introduction/Results/Discussion/Conclusion 的源依据，再与候选对应；新上下文审查核对作者为什么选择，不能由编号、图的最后节点或最低 IC50 自动生成。

## 方案权衡

1. **推荐：独立结构化标注**。支持多起点、多优选、证据、审核和快照；需要完整后端与前端契约。
2. Compound 两个 boolean：实现简短，但难表达多个系列、理由、来源和未决，不适合科学归档。
3. 继续仅写 description：当前兼容方案，可先记录事实，但不能可靠搜索、汇总或显示有依据徽标。

采用方案 1；CandidateEnvelope v1 增加可选 compound_highlights，旧候选省略该字段的序列化不变。

## 实施与验收

1. 新建独立标注实体、0030 迁移；同篇外键、唯一性、权限/CSRF、乐观版本和历史。
2. 贯通 AI 可选契约、draft apply、引用回执、导出与独立 review_metadata；旧 payload/hash 兼容。
3. 人工编辑、两组卡片、Compound 徽标、图上标签和来源详情、冻结/发布显示；中英文可切换。
4. 以合成 PDF 测试复现异步换页、URL 切换、未完成选区和窄屏几何；再修渲染与取消。
5. 更新当前科学及 reviewer 指导；独立临时 PostgreSQL 串行测试，前端测试/类型/浏览器检查。
6. 备份并仅迁移现有 Preview schema；比对既有数据、草稿和人工修改，记录交接。不部署生产。
