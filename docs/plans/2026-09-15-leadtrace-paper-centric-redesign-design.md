# LeadTrace 文章中心化数据与审核流程重建设计

**状态：已确认（Approved）**

**日期：2026-09-15**

**范围：20 篇 Source PDF 试点、PostgreSQL 科学数据模型、人工/AI 双入口、Reviewer 工作区、Admin 审批和文章级发布**

## 1. 背景

现有 LeadTrace 把首次发布、AI baseline、通用 revisioned object、changeset 和 Release
紧密耦合。它可以表达复杂的版本与发布状态，但也导致 Reviewer 无法从一篇只有 PDF
和书目信息的空文章直接开始核查；科学对象、机器 Proposal 和发布快照之间的关系也过于
复杂。

项目已经将旧业务数据完整备份并清空 PostgreSQL，只保留数据库结构和一个可登录 Admin。
`source_pdfs/` 继续作为只读源语料，旧 Dashboard 在 `127.0.0.1:8765` 独立运行用于对照。
新的 LeadTrace 可以在不迁移旧科学数据的前提下重新建立模型和页面。

## 2. 已确认的产品决策

1. PostgreSQL 继续作为权威业务数据库。
2. 第一版只选择 20 篇文章，先实现可完整使用的闭环。
3. 每个 Source PDF 对应且只对应一条 Paper 目录记录。
4. 基础目录不依赖科学 AI，包括 ID、标题、年份、Volume、Issue、DOI 和 PDF 身份。
5. 所有文章使用同一个固定模板，Reviewer 不能动态创造字段类型。
6. 模板中的 Compound、Lineage、Edge、Evidence、Activity 等条目数量可以变化。
7. Reviewer 可以把没有相关内容的区段明确标记为 `not_reported`。
8. Paper 可以不经过 AI，直接分配给 Reviewer 从空白开始填写。
9. AI 只是一种可选的预填方式，写入与人工相同的 Paper Workspace。
10. 每个 Compound 最多只有一个当前 Structure，不建立 Structure Proposal 候选池。
11. 不保存或展示 AI 置信度。
12. AI 初始值、Reviewer 每次修改、Reviewer 提交和 Admin 决策都必须保留历史。
13. Reviewer 提交后必须经过 Admin 审批，批准后才生成正式文章版本。
14. 一篇 Paper 可以有多条相互独立的 Lineage。
15. 一条 Lineage 可以有多个 root、intermediate 和 terminal Compound。
16. Edge Evidence 主要证明 Compound 之间的直接优化关系。
17. Structure Source Image 主要证明一个 Compound 的分子结构。

## 3. 目标与非目标

### 3.1 第一版目标

- 将固定的 20 个 PDF 建立为 20 条唯一 Paper 目录记录。
- 允许 Admin 创建 Reviewer、分配 Paper，并选择是否先运行 AI 预填。
- 允许 Reviewer 完全从空白工作区建立科学记录。
- 支持 Compound、唯一 Structure、结构原图、Lineage、Member、Edge、Evidence 和
  Activity 的类型化编辑。
- 支持 Ketcher 人工绘制、后端 RDKit 验证和统一二维重绘。
- 支持从 PDF 页中框选结构原图或 Edge Evidence，并保留可重建的来源定位。
- 保存每次 AI 和人工修改的不可变历史。
- 冻结 Reviewer Submission，支持 Admin 退回、重新提交和批准。
- 网站只把批准后的 Published Paper Version 当作正式科学数据。

### 3.2 第一版非目标

- Reviewer 已编辑后进行 AI 智能合并或局部接受建议。
- 多个 Structure Proposal、结构置信度或候选排名。
- 拖拽式 Lineage 图编辑和自动覆盖 root/terminal。
- 跨 Paper Compound 去重或全库化合物主数据。
- 多 Reviewer 同时编辑同一篇 Paper。
- 字段级 Admin 审批。
- 多盐型、多构象或多 Structure 版本同时作为当前值。
- 自动单位换算或跨论文 Activity 标准化。
- 恢复旧系统复杂的首次 baseline Release 和批量 Release 前置流程。
- 自动拆分复杂 Scheme 中的所有分子。

## 4. 方案选择

采用“规范化关系表 + Paper 聚合边界 + 追加式修改历史 + Submission 快照”。

不采用每篇 Paper 一个大 JSONB 文档，因为它无法稳定约束 Compound 与 Structure 的
一对一关系，也不利于跨文章查询、索引和局部修改。Submission 和 Published Version
仍使用 JSONB 快照，以便冻结一整篇文章并进行内容哈希。

不采用完整事件溯源。当前关系表直接表示可编辑工作状态，`change_events` 仅承担审计、
Diff 和恢复证据，不要求每次读取都重放事件。

“按文章分割”是业务、权限和事务边界，不是为每篇文章创建物理表。每一条科学记录都
直接包含或通过受约束外键严格推导出 `paper_id`。

## 5. 总体数据流

```text
20 个只读 Source PDF
        |
        v
Paper Catalog（单值基础信息，与 PDF 一一映射）
        |
        +---------------------------+
        |                           |
        v                           v
Admin 直接分配                 AI 预填空 Workspace
        |                           |
        +-------------+-------------+
                      v
              Reviewer Paper Workspace
              Compound / Structure
              Structure Source Image
              Lineage / Member / Edge
              Edge Evidence / Activity
                      |
                      v
              Reviewer Submission
                 immutable snapshot
                      |
             +--------+---------+
             |                  |
             v                  v
        Admin 退回           Admin 批准
             |                  |
             v                  v
       继续编辑并重提       Published Paper Version
```

## 6. 20 篇试点和基础目录

第一版使用 `source_pdfs/volume67 issue5/` 中按文件名排序后固定选择的前 20 篇 PDF。
选择结果写入版本化 Pilot Manifest，后续目录新增文件不会改变试点范围。

基础导入只使用确定性解析，不运行科学 AI：

- 从受控目录名解析 Volume 和 Issue；
- 从 PDF 元数据、第一页文本和文件名解析标题与年份；
- 从第一页文本使用确定性规则提取 DOI；
- 读取页数、文件大小并计算 SHA-256；
- 为每篇文章生成内部 UUID 和人可读 `paper_key`。

推荐的基础表：

### 6.1 `paper_sources`

- `id` UUID primary key
- `storage_key` unique，受控相对定位，不保存绝对路径
- `original_filename`
- `sha256` unique
- `byte_size`
- `page_count`
- `mime_type`
- `integrity_state`
- `created_at`

### 6.2 `papers`

- `id` UUID primary key
- `paper_key` unique，例如 `LT-JMC-2024-67-05-001`
- `source_id` unique foreign key to `paper_sources`
- `title`
- `journal`
- `publication_year`
- `volume`
- `issue`
- `doi` nullable unique
- `bibliographic_status`: `extracted` 或 `verified`
- `created_at`、`updated_at`

Source 身份、SHA-256 和映射不能由 Reviewer 修改。Reviewer 可以纠正书目信息，纠正
进入 `change_events`，并随 Submission 交给 Admin 审批。

## 7. 工作流表

### 7.1 `review_tasks`

- Paper、assigned Reviewer、created Admin
- 状态：`assigned`、`in_progress`、`submitted`、`changes_requested`、`approved`
- 同一 Paper 第一版最多一个非批准任务
- `version` 用于乐观并发控制

### 7.2 `paper_workspaces`

- 每个当前 ReviewTask 对应一个 Workspace
- 保存 `paper_id`、`review_task_id`、`version` 和编辑状态
- 空白人工路径不需要 baseline 或 base release
- Submission 后只读，Admin 退回后恢复编辑

### 7.3 `paper_section_reviews`

固定区段：

- `bibliography`
- `compounds`
- `structures`
- `lineages`
- `edge_evidence`
- `activities`

状态：`pending`、`completed`、`not_reported`。Reviewer 提交前每个区段都必须得到明确
处置；`not_reported` 可以附加说明，不需要创建占位科学条目。

## 8. 科学数据模型

### 8.1 Compound

`compounds` 包含 `id`、`paper_id`、`workspace_id`、`compound_label`、`display_name`、
`description`、`sort_order`、`created_by_kind` 和时间戳。同一 Paper 内 Compound label
需要唯一或显式允许 Reviewer 解决冲突。

### 8.2 Structure

`structures.compound_id` 设置唯一约束，每个 Compound 最多一个当前 Structure。字段包括：

- `smiles`
- `canonical_smiles`
- `molfile`
- `inchi`
- `inchikey`
- `structure_status`: `draft`、`reviewer_confirmed`、`unresolved`、`not_reported`
- `input_method`: `ai_prefill`、`manual_smiles`、`structure_editor`

不保存置信度，不建立 Proposal 表。AI 和 Reviewer 修改同一条 Structure。无效输入可以
作为 Draft 暂存，但不能进入 `reviewer_confirmed`；canonical 信息只能由后端 RDKit 生成。

### 8.3 Structure Source Image

`structure_source_images` 绑定 Compound 而非强制绑定 Structure，以便 Structure 尚未解析时
仍能保存证据。字段包括 Source PDF、page、归一化 bounding box、crop asset、来源上下文、
标签和 Reviewer note。

一个 Compound 可以有多张原图；复杂页面通过多次框选形成多个局部记录。证据身份由
`source_sha256 + page + normalized bbox` 决定，crop 只是可重新生成的派生资产。

### 8.4 Lineage、Member 和 Edge

一篇 Paper 可以有多条 Lineage。`lineage_members` 连接 Lineage 与 Compound，并保存角色：

- `root`
- `intermediate`
- `terminal`
- `unspecified`

`lineage_edges` 保存 parent、child、relation type、modification summary、review status 和
显示顺序。约束包括：

- parent 不等于 child；
- 两端属于同一 Paper；
- 两端已经属于该 Lineage；
- 同一 Lineage 内不重复创建相同有向边。

第一版由 Reviewer 明确设置 Member 角色，图拓扑仅用于显示和提交校验，不自动覆盖角色。

### 8.5 Evidence 和 Edge Evidence Link

`evidence` 保存 text、table、scheme 或 image 来源，包括 PDF、page、bbox、quoted text、
caption、crop asset 和 note。`edge_evidence_links` 把一条 Evidence 关联到一个或多个 Edge，
role 为 `supports`、`contradicts` 或 `contextual`。

已确认的 Edge 提交时至少需要一条 `supports` Evidence。无法确认直接关系时保留 Compound，
但不创建虚构 Edge。

### 8.6 Activity

第一版字段限于 Compound、assay name、metric、operator、value、unit、context 和可选 Evidence。
不进行自动单位转换或跨 Paper 归一化。

## 9. 修改历史、提交和发布

### 9.1 `change_events`

每个工作区写操作在同一 PostgreSQL 事务中：

1. 更新当前关系表；
2. 递增 Workspace version；
3. 追加不可修改的 Change Event。

Change Event 保存 `paper_id`、`workspace_id`、entity type/id、action、before/after JSONB、
actor kind/id、可选 AI run id 和 timestamp。删除也保存完整 `before_value`。

### 9.2 `paper_submissions`

Reviewer 提交时锁定 Workspace，验证完整性，并冻结全 Paper JSONB snapshot、内容 SHA-256、
submission number、workspace version、Reviewer note 和提交时间。旧 Submission 永不修改。

### 9.3 `admin_decisions`

Admin 对明确的 `submission_id + content_hash` 执行 `approve` 或 `request_changes`，必须填写
原因，并使用 Idempotency Key 防止重复操作。

退回会恢复 Workspace 编辑并保留旧 Submission。批准会创建不可变
`published_paper_versions`。正式文章页面只读取批准快照，不读取当前 Workspace。

第一版按 Paper 独立发布，不引入批量 Release；以后可以把多个 Published Paper Version
编组成数据集 Release。

## 10. AI 预填

`ai_extraction_runs` 保存 paper/workspace、启动版本、运行状态、引擎版本、错误摘要和时间。
不保存置信度。

第一版只允许 AI 写入尚未发生 Reviewer 修改的空 Workspace：

1. Celery 任务开始时记录 Workspace version；
2. 在隔离结果中完成全文提取；
3. 提交前重新锁定并比较 version；
4. Workspace 仍为空且版本一致时，在一个事务中写入全部记录和 Change Events；
5. 已有 Reviewer 修改时整次放弃，不做部分合并；
6. AI 失败时只更新 Run 状态，Workspace 不产生半套数据。

AI 可预填 Compound、唯一 Structure、Structure Source Image、Lineage、Member、Edge、
Evidence 和 Activity。Reviewer 直接编辑这些当前记录，AI 原始值保留在历史中。

## 11. 页面结构

### 11.1 Admin

- `/admin/papers`：20 篇紧凑目录表，显示基础信息、Source 状态、Reviewer、进度、AI 和提交状态。
- `/admin/papers/:paperId`：核对书目信息、查看 PDF、分配 Reviewer 或启动 AI。
- `/admin/submissions`：待审批队列。
- `/admin/submissions/:submissionId`：PDF、完整 Lineage、结构原图与 RDKit 图、Evidence、
  AI 到 Reviewer Diff，以及批准/退回操作。

### 11.2 Reviewer

- `/review/tasks`：只展示分配给当前 Reviewer 的 Paper。
- `/review/papers/:paperId`：固定标签页：文章信息、化合物与结构、Lineage、证据与活性、
  检查与提交。

Compound 页面使用列表与编辑器布局。Ketcher 作为成熟结构编辑器嵌入 Vue 应用，输出
Molfile/SMILES；后端 RDKit 校验、canonicalize 并生成二维图。

Lineage 第一版用表单创建 Member 和 Edge，用 Cytoscape.js 显示只读图，不做拖拽写入。

PDF.js 继续负责受保护 PDF 阅读。Reviewer 框选区域后，后端复用现有 PyMuPDF crop 管线。

### 11.3 已批准数据

- `/papers`：只列出存在 Published Paper Version 的文章。
- `/papers/:paperId`：显示批准后的书目信息、Compound/Structure、Lineage、Evidence 和 Activity。

未提交或未批准的 Workspace 数据不会进入正式文章页面。

## 12. API 与事务边界

采用 `/api/v2` 类型化端点，分别提供目录/分配、Workspace 聚合读取、各实体 CRUD、区段处置、
提交、审批和正式数据读取。正常 Reviewer 页面不提供通用 JSON 编辑器。

每个写请求携带 `expected_workspace_version`。版本不一致返回 `409`，不执行最后写入覆盖。
Submit、Admin Decision 和 AI apply 均使用行锁和单一事务。

权限边界：

- Reviewer 只能读取和修改分配给自己的活动 Workspace；
- Admin 可以查看全部目录、分配任务和审批；
- 正式数据读者只能看到批准快照；
- 所有 PDF 和 crop 通过受保护 Asset API 访问；
- API 不返回主机绝对路径或凭据。

## 13. 校验与错误处理

- PDF 缺失或 SHA-256 改变：Paper 进入 `source_error`，禁止分配和审批。
- 页码或 bbox 越界：拒绝保存并返回字段级错误。
- SMILES 无法解析：允许保留 Draft 输入，但不能 Reviewer Confirm。
- Edge 跨 Paper、自连接、端点不属于 Lineage：数据库和 API 双重拒绝。
- 已确认 Edge 没有 supports Evidence：允许草稿，提交时阻止。
- crop 失败：保留 locator，支持重试，不丢 Evidence。
- AI 失败：只记录 Run 失败，不修改 Workspace。
- 并发冲突：返回 `409` 和当前版本，第一版不自动合并。
- Admin 退回必须填写原因。

Reviewer Submit 至少要求：所有固定区段已处置；Structure 为 confirmed、unresolved 或
not_reported；Edge 合法且有支持 Evidence；Lineage 的 root/terminal 得到明确处置；Reviewer
完成整篇确认声明。

## 14. 迁移和部署

保留现有用户、认证、受控 Asset、审计、PDF 读取、crop 和 RDKit 能力。替换旧的 import、
revision、release、science 和 review 业务模型。数据库当前为空且已有完整备份，因此使用新的
Alembic revision 进行受控切换。

开发在独立 Worktree 和测试数据库中完成。当前 `:8876` 实例在最终验收前不应用新迁移；
旧 Dashboard `:8765` 保持只读对照。切换前再次备份当前空数据库和运行配置。

## 15. 实施顺序

1. 新 Schema、约束、20 篇 Pilot Manifest 和确定性建档。
2. Admin 文章目录、Reviewer 管理和任务分配。
3. 空白 Reviewer Workspace、区段状态和 Change Events。
4. Compound、唯一 Structure、Ketcher/RDKit 和 Structure Source Image。
5. Lineage、Member、Edge、Evidence 和 Activity。
6. Reviewer 校验与不可变 Submission。
7. Admin Diff、退回、重新提交和批准。
8. 正式文章列表与详情。
9. AI 预填和禁止覆盖人工修改的事务保护。
10. 20 篇试点、备份恢复、浏览器和部署验收。

## 16. 验收标准

- 固定 Manifest 中 20 个 PDF 对应 20 条唯一 Paper，SHA-256 和相对路径一致。
- 一篇 Paper 能够完全不运行 AI，从空白分配到 Reviewer 并获得 Admin 批准。
- 一篇 Paper 能够先 AI 预填，再由 Reviewer 修改并获得批准。
- Reviewer 可以添加、编辑和删除可变数量的科学条目，所有变化都有历史。
- 每个 Compound 最多一个 Structure，没有置信度或 Proposal 列表。
- Reviewer 可以输入 SMILES 或用 Ketcher 绘制，并看到 RDKit 统一重绘。
- Reviewer 可以从 PDF 框选结构原图和 Edge Evidence。
- 多 Lineage、多 root、多 terminal 和分支 Edge 能正确保存和显示。
- 空区段可以明确标记 `not_reported`。
- 缺 Evidence、无效 confirmed Structure 和非法 Edge 会阻止提交。
- Submission 冻结且可验证 content hash；Admin 退回后可以生成新的 Submission。
- Admin 只能批准明确的 Submission，批准后正式页面读取该快照。
- AI 与 Reviewer 发生版本竞争时，AI 整体放弃且不覆盖人工修改。
- Reviewer 越权、未批准数据泄露和 Source 绝对路径泄露测试均失败关闭。
