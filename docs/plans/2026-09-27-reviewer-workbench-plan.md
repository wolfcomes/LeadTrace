# Reviewer 工作台与指导文档改进计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> 用户已于 2026-09-27 批准实施；新增 Node 通过画布按钮选择本篇已有 Compound。执行者不限 Claude；继续工作时应遵守当前会话和仓库规则，不自动启动子代理。

**Goal:** 完成用户提出的七项改进，让 reviewer 看得懂字段、查得到术语、顺畅编辑复杂 lineage，并减少重复的检查与提交操作。

**Architecture:** 保留现有 Paper → Workspace → Compound / Structure / Lineage / Edge / Activity / Evidence 模型和版本化修改服务。复用同一套编辑逻辑提供表单与图形两种入口；将图形布局、浏览进度与科学内容的审核状态分别保存。新文章信息贯通预填、人工编辑、快照和发布，现有数据保持兼容。

**Tech Stack:** Vue 3、TypeScript、Cytoscape、FastAPI、SQLAlchemy、PostgreSQL、Alembic、Vitest、Playwright。

---

## 0. 状态、范围和已确认决定

日期：2026-09-27。

用户已批准实施全部七项。当前实现已完成并通过前后端及真实浏览器检查；本轮更新现有 Preview 的界面和 schema，不调用 DeepSeek、不重新提取论文、不部署生产、不整树提交已有改动。

目标工作树：`/data/home/zhangzhiyong/lead_optimization_collection/.worktrees/ai-prefill-tools`，分支 `codex/ai-prefill-tools`。工作树已有多轮未提交改动，后续实施应按功能形成可单独审阅的差异，不整树覆盖或提交。

| 决定 | 推荐方案 | 当前状态 |
|---|---|---|
| “图／Compound／Edge 三栏、允许切换” | 三个页签，各占主要区域；保持选择、筛选、滚动和画布状态 | 用户 2026-09-27 已确认 |
| “阅读后自动确认” | 自动记录已查看、汇总检查项；保留最后一次提交确认，不自动清除疑点或把结构/Edge 改为科学审核通过 | 用户 2026-09-27 已确认 |
| `-Be` 指什么 | 不预设；列为待澄清的缩写，可能需与 `Bn`／`Ph` 区分 | 非阻塞；先整理无歧义术语 |
| 布局持久化 | 保存当前 workspace/lineage 的共享布局，刷新后可恢复；个人缩放/平移单独保存 | 推荐默认，可在实施前调整 |
| PDB ID“截取” | 提取正文中提及的 ID、源位置和用途；提供外链。此期不默认下载坐标或加入三维查看器 | 推荐默认，可在实施前调整 |

以上两个主要交互已确认。其余使用表内推荐默认值；`Be` 不阻塞无歧义术语的整理。用户随后已明确批准开始实现；本文保留设计依据，最终实现说明见末尾。

### 方案比较与选择

1. **推荐：分阶段完善现有工作台。** 三视图切换＋统一表单/图编辑＋持久布局＋查看进度＋文章补充信息。一次解决实际操作问题，复用现有服务，逐阶段展示效果。
2. **全功能三栏画布。** 图、成员、关系同时并排，支持复杂连线工具和多窗格。宽屏比较方便，但窄屏、编辑器宽度、键盘焦点和布局持久化更复杂；用户已选择三个页签，本期不采用并排布局。
3. **只做提示和文档。** 改动小、交付快，但不能解决复杂 lineage 长页面和重复确认问题，不作为七项任务的完整交付。

## 1. 已核实的现状

以下路径均相对目标工作树。

- `leadtrace/frontend/src/review/paper/LineageEditor.vue`：图、Member 列表、Edge 列表在同一主体中纵向排列；点击 Edge 会进入关系详情。
- `LineageGraph.vue`：基于 Cytoscape，`autoungrabify: true`；只能点边查看，不能在图上新增。点线图与结构图都有；当前重建图时重新布局，只在组件内保留部分缩放和平移，无持久节点坐标或边曲线控制点。
- `CompoundList.vue` / `EdgeEditor.vue` / `ActivityEditor.vue` / `EvidenceEditor.vue`：已有新增与编辑表单，可复用；示例和填写说明不统一。
- `PaperWorkspacePage.vue`：文章信息主要显示标题、期刊、DOI、卷期。`papers/models.py`、Workspace bibliography schema、AI payload 都没有 Abstract/PDB 专门字段；后端已有版本化 bibliography 编辑接口。
- `SectionStatusControl.vue`：六个区段分别手动设置 pending/completed/not_reported。
- `SubmissionChecklist.vue`：服务端校验＋最终整篇 checkbox＋提交。`workspaces/validation.py` 还要求 Structure/Edge 有科学处理状态，并检查 lineage root/terminal 和跨工作区引用。仅前端把区段涂成“已读”不会消除这些要求。
- `review_hint` 已存在：Compound/Activity/Edge 的疑点是独立提示，不能被阅读动作自动清除。
- 当前没有一份完整、面向 reviewer 的统一操作手册；AI 提取指南与 reviewer 手册用途不同，应链接共享科学规则，避免重复维护相互矛盾的定义。
- 最近交付的 F 版在 Preview 显示为未经过独立复核的草稿；本计划不把该状态改成已审，不恢复或重跑 F 科学任务。

## 2. 七项功能设计

### 2.1 空白字段与空列表示例

将“格式示例”“未填写”“原文未报告”区分开。

- 简短示例放 placeholder；容易出错的字段同时有始终可访问的帮助说明，输入后仍能查看格式。
- 空列表放一张明确标注“格式示例，不会保存”的示意卡或折叠说明，并保留新增按钮。
- 示例来自合成示例数据，不冒充本篇论文结论；不预填到业务值，不因提交空表单保存 eg。
- 下拉枚举给出中文/英文解释；单位、数值、运算符分开输入。只有真实数值填数值框，`>`、`ND`、`±` 不混成一个数。
- 无需给每个常识性字段增加长段文字，优先覆盖编号、SMILES、成员角色、关系类型/说明、Activity、Evidence、review_hint、Abstract/PDB。

| 位置 | 示例/说明形式 |
|---|---|
| Compound label | `例如：24`；保留论文原始编号，不自行续号 |
| SMILES | `例如：CCO（仅格式示例）`；不能用基团缩写替代完整结构 |
| Lineage 名称 | `例如：苯环取代基优化系列`；合成路线与 SAR 分开 |
| Edge 说明 | `例如：对位取代基由 Me 改为 OMe；比较同一测定条件下的活性。` |
| Activity | 分栏示意：assay、IC50、`=`、`12.5`、`nM`、测定条件；示例值不得自动保存 |
| Evidence | 源页号、Table/Scheme/Figure、对应区域或原文摘录，附一条格式示例 |
| 需核对 | `依据共用骨架和 R 基推导；中间体与产物的编号对应仍需核对。` |

验收：未操作的空字段始终为空；输入后说明仍可打开；帮助可键盘访问；中英文布局正常；没有 tooltip-only 的必要说明。

### 2.2 基团缩写速查文档

创建一个版本化、可搜索的标准数据源，生成网页速查和人可阅读文档，避免网页与 Markdown 手工维护两份。

建议字段：`abbreviation`、中文名称、英文名称、连接形式、别名、类别、歧义提醒、来源说明。按大小写和连接位置区分；通用缩写是辅助，论文的明确自定义图例优先。

第一批明确收录：

| 缩写 | 意义 | 连接形式/提醒 |
|---|---|---|
| Me | 甲基 / methyl | `–CH3` |
| Et | 乙基 / ethyl | `–CH2CH3` |
| n-Pr / i-Pr | 正丙基 / 异丙基 | 不能忽略支化 |
| n-Bu / i-Bu / s-Bu / t-Bu | 不同丁基 | 保留前缀 |
| Ph | 苯基 / phenyl | `–C6H5` |
| Bn | 苄基 / benzyl | `–CH2C6H5`，不同于 Ph |
| OMe | 甲氧基 / methoxy | `–OCH3`，连接原子为 O |
| OBn | 苄氧基 / benzyloxy | `–OCH2C6H5` |
| Ac | 乙酰基 / acetyl | `–C(=O)CH3`；与元素/其他语境区分 |
| Boc / Cbz / Fmoc | 常用保护基 | 标明连接位置与脱保护语境；不直接当完整分子 |
| Ts / Ms / Tf | 磺酰基简写 | 区分 Ts/OTs、Ms/OMs、Tf/OTf 的连接 |
| Ar / HetAr / R | 芳基、杂芳基、可变取代基 | 不代表唯一完整结构 |
| o- / m- / p- | 邻、间、对位 | 位置前缀，不是独立基团 |

`Be` 是铍的元素符号，不应自动解释为苄基或苯基；若论文另有定义应按该论文记录。第一版不为不明缩写自动补结构，也不自动把用户的 SMILES 文本替换成缩写展开结果。

网页入口：字段旁“基团速查”打开可搜索面板；手册链接同一目录。数据源建议 `docs/reviewer/functional-groups.json`，生成 `docs/reviewer/functional-groups.md`，网页通过构建脚本读取同一数据。

验收：Me/OMe、Ph/Bn、Ts/OTs 可明确对照；不认识的缩写显示待查；生成文档与数据一致；中文/英文搜索都能找到对应条目。

### 2.3 Lineage 三个独立视图（用户已确认三个页签）

推荐页面结构：

```text
Lineage 类别和目录：SAR / 合成 → 当前 lineage
当前 lineage 标题、简介、计数
[ 图 ] [ Compound（当前 lineage 成员） ] [ Edge ]
└─ 当前视图占用主要区域，内部滚动
```

- 此处 Compound 指本 lineage 的成员视图，不复制文章级 Compound 数据。
- 三个视图共用当前 lineage、选中 compound/edge 和过滤条件。成员页签显示角色、结构缩略图、需核对与“打开文章级详情”。
- 图上点节点 → 打开对应成员；点边 → Edge 视图定位该条。返回图保留缩放、坐标、选择。
- 只有当前视图的主内容可见，避免图、全量成员、全量关系同时堆成长页面。Evidence 保留在选中 Edge 的详情中，另有现有证据库入口。
- 页签切换、语言切换、返回时不丢未保存编辑；需要离开有草稿的 lineage 时保留草稿或明确提示，不静默丢失。
- 目录也有界滚动，避免只改主区却继续被全部成员摘要拉长。
- 本期不增加三栏并排切换，以免形成两套布局操作；窄屏也使用同样三个页签。

验收：用合成的 120 节点/180 边场景验证，不必向下穿过全部成员才能操作 Edge；点选能互相定位；切换不触发整图重新洗牌。

### 2.4 图上新增和拖动 Node / Edge

明确区分“增加图中的成员”与“创建新的科学记录”。

**两种新增入口，共用一套业务命令：**

1. 原有表单继续使用。
2. 图工具栏提供“添加节点”“添加关系”；在画布指定位置发起，打开相同的选择/编辑表单。

按用户最终确认：画布按钮只选择本篇已有 Compound，再创建 Lineage Member。不存在的 Compound 先在文章级化合物页创建；画布不创建空白 Compound。选择弹窗取消不写记录。

新增关系使用明确模式：先选择 Parent，再选择 Child，显示方向预览，再填写关系类型、说明/需核对后保存。首版不需要复杂拖拽插件；普通拖节点不会误创建 Edge。支持 Esc 退出；自环、跨 lineage/paper、重复请求遵循服务端规则，版本冲突后重新核验端点。

**手动布局：**

- Node 可拖动；连线随两端移动。
- Edge 不是独立节点。选择边时提供控制点调整弯曲/绕行；拖控制点不更改 Parent/Child、不反转关系。不把拖边离开节点解释成删除或改端点。
- 首版控制为单个曲线控制点（及需要时的标签位置），不做复杂任意折线绘图器。实现前用真实 Cytoscape 验证曲线控制能力，不承诺已有插件直接可用。
- 提供“保存布局”“恢复自动布局”和本次未保存布局撤销；重置自定义布局要有明确意图。
- 布局建议按 workspace＋lineage＋点线/结构模式持久化；坐标用模型坐标而非浏览器像素。缩放/平移是个人视图偏好。
- 新增节点只对新增部分给初始坐标；已有节点保留位置；删除节点清理坐标；角色变化不重排整图。
- 数据修改只复用现有 Member/Edge/Compound 服务与 workspace 版本，不在 Cytoscape 中私自形成另一份科学数据。
- 布局保存使用独立 presentation revision，避免拖动几次就使科学审核全部失效。保留作者/时间和变更追踪；提交可冻结布局供管理员重现，布局不影响候选科学 hash。
- 只读页面可缩放/平移；不可新增科学记录或保存共享布局。

验收：两入口生成相同业务结果；失败不留幽灵节点；拖动不改变关系身份；刷新、切页签和重开文章后布局能恢复；共同编辑发生冲突时不覆盖新布局。

### 2.5 Abstract 与 PDB ID

**Abstract：**

- 文章信息区增加可编辑摘要，保存原文语言与段落；不自动总结成另一篇摘要。
- 可附来源页号/上下文，未提取、原文没有、待核对分别说明；不能用全文首段当作默认摘要。
- 缺省可为空，旧文章不因此新增硬性提交障碍。

**PDB 记录：**

- 一篇文章支持多个 ID，去重但保留不同提及的来源位置。
- 最小内容：ID、源页号/上下文、用途（本文结构／引用既有结构／未确定）、可选 Compound 关联、可选简短需核对说明。
- 不是所有提到的 PDB 都是本文新沉积结构；也不是所有 PDB 都能与一个 Compound 一一对应。不明时保持未确定。
- ID 可打开 RCSB 条目；首版不下载坐标、不嵌入三维查看器、不因外站不可用阻止保存。
- 区分 PDB accession 与 ligand/chemical component 的代码，不从任意四位字符串猜测。实施前核对 RCSB 当前公开标识规范，兼容旧 ID 与官方扩展格式，不把数据库永远锁成四字符。

**数据流：**

- 摘要可沿用现有 Paper bibliography 编辑/历史边界；另存可选来源信息。
- PDB records 建议为 workspace-scoped 子记录（paper_id＋workspace_id），约束源和可选 Compound 关联均属于当前工作区；快照/发布保存完整值，不在已发布文章实时回查可变草稿。
- Workspace/API、后台目录详情、Admin submission、Published Paper 同步支持。
- AI payload/schema/当前提取指南增加可选字段；旧候选缺省字段仍按原序列化计算哈希，验证 A–F 历史候选不失效。若无法无损兼容，应明确升契约版本，不能静默修改旧候选。
- 本阶段先交付字段、人工编辑和新提取契约；不自动批量补写旧文章。原文读取仍由 DeepSeek 完成；真实抽取试验需另建任务包。

验收：多 ID、不同用途、重复提及、错误 ID、无摘要/无 PDB、老候选/老快照均有测试；新增后经过“编辑→提交快照→Admin→发布”不丢失。

### 2.6 自动记录已读与简化检查提交（语义已确认）

推荐用界面词“已查看 / 未查看”，系统只能记录页面交互，不能证明人已经理解或核实科学内容。

**读取触发与标记：**

- 用户主动打开具体记录详情、内容成功加载且在前台可见后记录已查看；不能因后台预加载、只打开顶层页签或列表里出现标题就全量标已读。
- Compound 信息、Structure、Lineage 摘要/成员、Edge、Evidence、Activity 分别统计。打开一个 Compound 不自动标记其尚未展开的全部 Activity/Evidence；大图出现 120 节点也不表示全部读过。
- 轻微背景色变化＋文字/小标记，选中态和 `⚠` 仍清楚；不能只靠颜色传意。
- 支持“标为未查看”，无需停留倒计时，也不对滚动距离假装做阅读证明。
- 记录由服务端保存，跨刷新/设备有效，绑定 reviewer、workspace、entity、内容签名和时间。阅读事件轻量幂等，不触发科学 workspace version 增长。
- 内容修改后，只使该条目及受影响的依赖重新变为未查看；例如 Structure 改变会影响该 compound 的结构核对以及相关 Edge，拖动图位置不会使科学条目重新未读。
- 签名由服务端生成并校验；客户端不能声明任意新 hash 以跳过失效。UI 显示计数即可，复杂签名不暴露给 reviewer。

**检查与提交如何真正减少操作：**

- 六区段检查页自动汇总当前版本的“已查看 x/y”与服务端缺陷，点击即可进入下一个未查看条目。
- 推荐去掉六区段重复的“阅读完成”手工勾选：当该区段应查看内容均已查看、必要科学状态已处理，自动满足其完成条件；真实“原文未报告”仍需 reviewer 明确说明，空列表不能自动推出未报告。
- 当前 Structure/Edge 的科学处理要求保留；新自动已查看不偷偷设置 reviewer_confirmed。阅读后有错可直接编辑，需保留疑点可显式标未解决，review_hint 只在解决后由人清除。
- 最终保留一次整篇提交确认＋一次提交按钮；Admin 审批流程保留。
- 提交时同一事务核对科学版本、当前查看覆盖和原有完整性规则；查看记录与编辑并发时不采用过时覆盖。阅读完成不能绕过跨论文引用、结构无效等硬检查。
- 当前仍有 pending 的历史 workspace 不自动变成已读；此前手动完成的状态保留历史，不冒充新的逐项查看回执。旧提交快照不回写。
- 用户已确认：自动记录已读，最终提交由 reviewer 确认；打开阅读不会把 Structure/Edge 自动设置为科学审核通过。

验收：后台载入不记已读；主动查看只影响相应记录；编辑能正确失效；跨账号不继承查看状态；无额外逐区段点击负担；最终提交仍产生不可变快照。

### 2.7 统一 Reviewer 指导文档

建立 `docs/reviewer/README.md` 作为唯一人工操作入口，中文主文与英文同版本配套；网站内有“Reviewer 指南”入口。基团速查和字段示例来自共用资源，避免三份不一致的格式说明。

建议目录：

1. 一页快速上手：打开任务 → 看文章与结构 → 检查 lineage/活性/证据 → 处理疑点 → 提交。
2. 哪些分子收录：编号/命名身份、有结构或可合理推导；没有活性也可能是必要中间体。
3. Compound 与 Structure、SAR 与合成、Member 与 Edge 的区别。
4. 每个字段的填写格式和例子；基团速查链接。
5. root/intermediate/terminal、作者优化终点的含义；角色按关系解释，不根据图的位置判定。
6. 不在 lineage 中的分子如何说明；无需为了连通虚构关系。
7. 图和表单两种编辑方式、手动布局与保存。
8. Activity 的单位、条件、运算符、缺报和冲突；Evidence 定位。
9. Abstract/PDB 的来源与用途，引用结构不等于本篇新结构。
10. `⚠ 需核对` 如何查看、保留和解除；未标记不等于已核实。
11. 已查看、科学已处理、提交给 Admin 的区别；退回后如何继续。
12. 常见错误与提交前示例清单。

指导文档应说明 UI 已实现能力；计划中的功能在交付前不写成已上线。科学规则链接当前 AI-prefill 指南的稳定条目，不复制整份运行指南，也不出现凭据、运维命令或测试数据。

## 3. 实施顺序与具体工作包

所有文件相对目标工作树。以下新建文件名为建议，执行时如已有对应模块应复用，不重复造相同组件。迁移编号以实施时实际 Alembic head 为准，不预占旧编号。

### 工作包 A：确认交互与建立共享帮助内容

修改/新建：

- `docs/reviewer/README.md`、`README.en.md`。
- `docs/reviewer/functional-groups.json`、生成的 `functional-groups.md`。
- `leadtrace/ops/docs/build_reviewer_reference.py`（生成/校验脚本）。
- `leadtrace/frontend/src/review/help/FieldHelp.vue`、`FunctionalGroupReference.vue`、字段示例资源。
- `CompoundList.vue`、`EdgeEditor.vue`、`ActivityEditor.vue`、`EvidenceEditor.vue`、`src/i18n/en-review.ts`。

步骤：

1. 采用第 0 节已确认的页签和已读语义；进一步整理非阻塞默认项。
2. 列出需示例的实际字段、可选/必填、单位/枚举约束。
3. 编辑基团数据和文档；人工核对歧义条目，未知术语不强行展开。
4. 实现轻量帮助组件与空状态示例；接入中文/英文。
5. 验证空表单不会保存示例，帮助可键盘访问；文案/纯样式不写镜像测试。

### 工作包 B：拆分 lineage 三视图

修改/新建：

- `leadtrace/frontend/src/review/paper/LineageEditor.vue`、`LineageGraph.vue`、`EdgeEditor.vue`。
- `useLineageViewState.ts`、必要的 Member/Edge 列表组件。
- `PaperWorkspacePage.vue`、`src/styles/components.css`、`src/styles/layouts.css`、i18n。
- `leadtrace/frontend/tests/lineage-editor-v2.spec.ts`、`lineage-molecular-navigation.spec.ts`、`lineage-view-state.spec.ts`（新）。

步骤：

1. 写视图切换/定位/未保存编辑保持的行为测试，确认旧行为失败。
2. 将共用选择和 mutation 逻辑保留在父层，仅拆显示和滚动区域。
3. 将图节点/边选择接到对应视图，保留深链接和现有“返回图”。
4. 修正图重建条件，切换视图不重新随机排布。
5. 用大数据浏览器用例核对图、成员、关系都无需穿过整页长列表。

### 工作包 C：图编辑和持久布局

修改/新建：

- `LineageGraph.vue`、`LineageEditor.vue`、`useLineageGraphEditing.ts`、`useLineageLayout.ts`。
- `leadtrace/backend/app/lineages/models.py`、`schemas.py`、`router.py`、`service.py`；可抽出 `presentation.py`。
- `leadtrace/backend/migrations/versions/<next>_lineage_presentation.py`。
- `leadtrace/frontend/src/v2/api.ts`、`types.ts`、`workspaces/snapshot.py` 和发布布局投影。
- 测试：`tests/science_v2/test_lineage_api.py`、新增 `test_lineage_presentation.py`、前端 `lineage-graph-editing.spec.ts`、`lineage-layout.spec.ts`。

步骤：

1. 写测试明确两入口共用业务服务、只读禁止写入、版本冲突处理。
2. 先实现图上选择已有 Compound＋添加 Member，再实现 Parent→Child 选择和关系表单。
3. 实现受控节点拖动，真实浏览器验证画布拖动与节点拖动不会混淆。
4. 最小原型验证 Edge 控制点，确认不会改拓扑后接入保存。
5. 新建布局表：workspace/lineage/mode、positions、edge controls、独立 revision、更新人/时间；验证实体引用范围、有限坐标、大小上限与乐观并发。
6. 实现保存、恢复、重置、局部新增布局；冻结提交布局但不改变科学候选 hash。
7. 测试失败回滚、删除引用清理、多标签页冲突、刷新恢复和旧无布局数据回退。

### 工作包 D：文章摘要与 PDB 信息贯通

修改/新建：

- `leadtrace/backend/app/papers/models.py`、新 `paper_structure_references` 模块或现有 papers/workspaces 内对应服务。
- `workspaces/schemas.py`、`router.py`、`snapshot.py`、`publications/schemas.py`。
- `ai_prefill/contracts.py`、`service.py`、`workspace_export.py`、`assistance_contracts.py`（按实际兼容需求）。
- `leadtrace/backend/migrations/versions/<next>_paper_abstract_pdb.py`。
- `PaperWorkspacePage.vue`、新 `BibliographyEditor.vue`、Admin/Published 页面、前端 `v2` schemas。
- `docs/ai-prefill/extraction-guide.md`、自检/审查规则、候选 schema：只增加对应字段和来源要求，不进行无关重写。
- 测试：新增 `tests/workspaces/test_paper_metadata.py`，扩展 `tests/workspaces/test_snapshot.py`、`tests/publications/test_api.py`、`tests/ai_prefill/test_contract.py` 与前端 metadata 测试。

步骤：

1. 明确可选字段与来源对象，核对官方 PDB ID 格式；写旧契约兼容测试。
2. 编写可回退的加字段/加表迁移，旧记录保留 null/空列表。
3. 实现版本化编辑、权限/关联约束和网页表单。
4. 贯通快照/发布和候选导入导出，测试旧候选 hash 不变。
5. 更新本功能的当前指南与 reviewer 说明；抽取测试另用新 bundle，不改 A–F。

### 工作包 E：已查看覆盖与检查提交流程

依赖：第 0 节语义已确认；实施时 B/C/D 的实体与展示边界需先稳定。

修改/新建：

- `leadtrace/backend/app/workspaces/review_progress.py`、`models.py`、`schemas.py`、`router.py`、`validation.py`、`submission.py`。
- `leadtrace/backend/migrations/versions/<next>_review_progress.py`。
- `leadtrace/frontend/src/review/paper/useReviewProgress.ts`、`SubmissionChecklist.vue`、`SectionStatusControl.vue`、具体详情面板。
- 前后端 API/types、i18n。
- 测试：`tests/workspaces/test_review_progress.py`（新）、`test_submission.py`、`test_concurrency.py`；前端 `review-progress.spec.ts`（新）、`submission-v2.spec.ts`。

步骤：

1. 将“哪些交互算查看”“哪些修改使它失效”“哪些原审核要求继续有效”写成测试矩阵。
2. 建立查看回执与内容签名服务；仅当前有权限 reviewer 的主动记录有效，接口幂等、有 CSRF/范围检查。
3. 将成功展示事件接到回执接口；不在通用 GET API 或组件后台 onMounted 时无条件记已读。
4. 增加轻微色差、文字状态和未查看筛选；失败可重试，不谎报服务端已保存。
5. 检查页自动汇总区段完成条件，取消重复阅读勾选；保留 not_reported 明确说明和必要科学 disposition。
6. 最终提交事务校验签名/科学版本，冻结需要的审核摘要；不修改历史 submission。
7. 验证多标签页/退回/重新分配/结构修订等场景；同一内容重复查看不膨胀科学版本。

### 工作包 F：指南定稿与整体验收

1. 用统一示例走一遍新人 reviewer 流程，修正手册和界面用词不一致。
2. 更新中英文帮助入口、基团速查、已读和疑点的说明。
3. 验证七项需求和下方验收矩阵，无科学状态误标。
4. 保存源码差异清单、验证结果和独立运行 handoff；经具体部署步骤后再展示 Preview，不以合并代替部署。

## 4. 验证与交付门槛

| 场景 | 必须证明的行为 |
|---|---|
| 空表单 / 空列表 | 示例不进入实际记录，未报告与未填写不混淆 |
| 基团速查 | Me/OMe、Ph/Bn 等差异清楚，未知术语不伪造结构 |
| 大 lineage | 图、成员、边切换与定位不丢状态；不需要整页反复长滚动 |
| 图上编辑 | 表单/图两入口结果一致，取消/冲突无幽灵记录 |
| 手动布局 | 坐标/曲线保存恢复；不修改端点、角色和科学审核状态 |
| Abstract / PDB | 可选数据贯通快照与发布；多用途、多 ID、缺项、老数据兼容 |
| 已查看 | 按具体记录而不是预加载计数；相关修改使其失效 |
| 提交 | 自动汇总减少手工步骤，最终确认/完整性/权限/不可变快照仍有效 |
| 语言与可访问性 | 中文/英文完整，键盘可操作，颜色不是唯一状态表达 |
| 既有 F 数据 | 候选/历史 bundle 不改；新 UI 不将其科学审核状态自动升级 |

前端在 `leadtrace/frontend` 执行：

```bash
npm test -- tests/review-hints.spec.ts tests/lineage-editor-v2.spec.ts tests/lineage-molecular-navigation.spec.ts tests/submission-v2.spec.ts
npm run typecheck
npm run build
```

随各工作包加入对应新测试；最终运行相关浏览器用例，特别是 **真实 Cytoscape 拖动、边控制点、刷新恢复和窄屏布局**，不能只依赖 jsdom 模拟。

后端数据库测试只能使用独立临时 PostgreSQL 集群，数据库名以 `_test` 结尾，先验证 endpoint/data_directory；在 `leadtrace/backend` 执行相关 suites，DB suite 串行：

```bash
../../.venv/bin/python -m pytest tests/workspaces tests/science_v2 tests/publications tests/ai_prefill/test_contract.py tests/db -q
../../.venv/bin/python -m compileall -q app
```

上面命令必须在显式配置 `LEADTRACE_TEST_DATABASE_URL` 后运行，不使用默认 live Preview/production 连接。具体新测试加入相应目录。若有新 route，补权限矩阵/CSRF 测试；如涉及旧候选序列化，做历史 hash 回归。

文档生成校验、`git diff --check`、离线 Alembic SQL、迁移回退/恢复验证也应按实际改动完成。低风险静态文案无需编写复述实现的测试。

## 5. 阶段交付与范围控制

建议分四次可查看交付：

1. 示例、基团速查、指南骨架＋lineage 三视图。
2. 图上新增与可保存的手动布局。
3. Abstract/PDB 数据与文档贯通。
4. 已查看进度、简化检查提交、完整指南和回归验收。

每一阶段先在独立测试环境验证，再按当前 Preview runbook 制作备份、核对实例和实际 workspace 版本，执行明确的 Preview 更新。保留用户在此期间的人工修改。源码合并不授权生产迁移/部署，不将 Preview 科学数据导入生产。

本计划不额外引入 PDB 三维查看器、自动化学命名器、概率评分、自动科学批准或 lineage“target”新科学角色。作者优化终点的说明可以在手册中澄清，专门的新字段若需要应单独明确。

## 6. 实现与验证（2026-09-27）

七项已实现。实际文件入口：

- 工作台：`PaperWorkspacePage.vue`、`LineageEditor.vue`、`LineageGraph.vue`、`BibliographyEditor.vue`、`useReviewProgress.ts`。
- 文章字段：`papers/metadata.py`；已读和布局 API：`workspaces/workbench.py`；内容签名：`workspaces/review_progress.py`；迁移：`0029_reviewer_workbench.py`。
- 统一内容源：`leadtrace/frontend/src/review/help/reviewer-guide.json`；中英文生成文档：`docs/reviewer/reviewer-guide.{zh,en}.md`；生成检查：`python leadtrace/ops/reviewer/render_guide.py --check`。

实现时采用的具体选择：

- PDB mentions 作为 Paper 上的结构化 JSON 列表，随 bibliography 使用现有版本化历史；逐项验证 ID/页码/枚举，Compound label 记录来源标签。此标签是来源说明，不构造未经核对的数据库外键。摘要/PDB 贯通候选、快照和发布；本轮不回填现有文章原文。
- 缩写表与指南合为同一双语数据源，在各编辑区可打开格式示例，在工作台顶部可搜索完整速查。
- 布局按 lineage＋模式独立保存 revision、作者、时间；提供保存、重排为网格和重新载入撤销。缩放/平移在当前组件内保留；刷新恢复保存的节点/曲线。此版不提供历史布局浏览或发布页图形重放；现有发布页继续展示不可变成员/关系数据。
- 查看回执按具体条目及其内容/依赖签名保存，不增加 workspace 科学版本；主动打开详情才记读，后台预取不记读。旧人工区段记录保持可用；一旦开始跟踪，提交时校验当前 reviewer 的完整查看覆盖。仍校验 Structure/Edge 科学处置，最终整篇 checkbox 由人确认。
- 合成大图为 120 节点／180 边，浏览器实际鼠标拖动与控制点、刷新恢复、现有 Compound 加入、图选端点到表单和分模式保存均已验证。

验证记录与 Preview 实例备份保存在忽略的 `leadtrace-data/reviewer-workbench-20260927/`，不把运行数据或凭据写入 Git。已有工作树的科学草稿和人工修改未作为本功能的一部分重写。

最终验证：前端 224 项通过；TypeScript 类型检查通过；4 项 Playwright 流程通过（包含 120 节点／180 边的大图操作、人工提交发布、AI 记录编辑保护和 Ketcher CSP）；最终生产构建通过。后端相关套件 146 项通过，随后工作台专项 6 项通过，均运行于独立临时 PostgreSQL。文档生成一致性与差异空白检查通过。

代码复核后补充了页签间未保存输入保护、结构后台刷新期间的输入保护，以及 Evidence 内容版本与查看回执绑定；创建 Evidence 后部分关联失败可继续重试，无需重复建 Evidence。Preview 已升级至 `0029_reviewer_workbench` 并更新界面；部署及只读复查确认既有科学数据、工作区版本和草稿状态保持不变。科学内容独立复核状态不因本轮软件验证而改变。

## 7. 用户试用后的修正（2026-09-27，已交付）

用户要求修正新增 Node 弹窗，并将自动已读简化为 Compound 和 Lineage 两层。本节取代前文逐结构、活性、Edge、Evidence 和文章信息记录 viewed 的设计。

- 弹窗不复用横排 inline-create-form；标题、说明、搜索、Compound、角色纵向排列，操作按钮独立一行，限制宽度并允许纵向滚动。浏览器验证中英文及窄屏控件边界，避免仅测试“弹窗存在”。
- 自动查看只保存 Compound/Lineage。Compound 签名覆盖自身、结构、来源图、活性及活性引用证据；Lineage 签名覆盖自身、成员、成员 Compound 内容、Edge、证据链接和关联证据。无关组改动不使其他组失效；布局不参与签名。
- 前端只显示两类查看计数，移除其余已读徽标和写请求。结构/活性区段的阅读条件由 Compound 覆盖，Edge Evidence 由 Lineage 覆盖；文章信息保留人工确认。无归属 Evidence 仍可在证据库查看，不新增虚构 Compound/Lineage，也不批量产生读回执。
- 已有逐项回执保留，不把旧窄范围阅读自动升级为整组阅读。新聚合签名需重新打开对应 Compound/Lineage。无须 schema migration；草稿、科学数据、布局和人工修改均保留。
- 顺序：复现弹窗边界失败及聚合签名测试 → 修复 CSS/两层 API 与调用/提交映射 → 同步双语指南 → 独立 PostgreSQL、前端与浏览器检查 → 当前 Preview 备份、重启、只读验证及 handoff。

本次验证：225 项前端测试、32 项后端相关测试、4 项 Playwright 流程、类型检查与构建通过；实际 Preview 的中文桌面和英文 390px 窄屏弹窗均验证无字段重叠或横向溢出。接口仅返回 Compound/Lineage 两类查看项和计数。schema 保持 0029，已有草稿、查看回执和图布局保持原数据；没有科学写入。详细交接在忽略目录 `leadtrace-data/reviewer-workbench-refinement-20260927/`。
