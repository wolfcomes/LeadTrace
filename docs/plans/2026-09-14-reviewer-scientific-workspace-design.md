# LeadTrace Reviewer 科学核查工作台设计

**状态：待确认（Draft）**

**日期：2026-09-14**

**范围：Reviewer 工作台、Paper 详情、核查任务内的首页 molecule-object 队列**

## 1. 背景与目标

LeadTrace 已经能够发布自动提取得到的 AI baseline，并通过独立的
`publication_status` 与 `verification_status` 区分“可发布”和“是否经过人工
核验”。现有核查生命周期、Region/Visual Object API、Structure 验证与绘图服务
以及 changeset 的提交/审批/发布机制也已经存在，但 Reviewer 页面仍有明显断点：

- Region、Visual Object 和 Structure 没有完整的专用编辑工作台，部分编辑仍退回
  直接修改 JSON。
- Paper 详情或 Reviewer 页面没有把 PDF crop、OCSR proposal、RDKit 图和来源
  定位放在同一个可比较的证据上下文中。
- `first_page_molecule_objects.csv` 已经进入视觉对象数据，但首页 molecule-object
  的待定位、待 OCSR、待确认状态没有在现有“核查任务”中形成清晰的工作队列。
- 当前 changeset 只要求至少包含一个 item 即可提交；审批时又会完成整条 ReviewTask。
  这不足以证明整篇 Paper 已完成核查。
- 发布 successor Release 时沿用了旧的 `human_review` 指标，不能可靠反映本次发布
  中真正完成 Paper 级确认的数量。

本设计的目标是：

1. 为 Region、Visual Object、OCSR Proposal 和 Structure 提供类型化、可审计、无需
   编辑 JSON 的 Reviewer 工作流。
2. 让 Reviewer 在一个稳定的三栏工作台中同时看到页面、crop、候选结构、RDKit 图、
   来源位置和当前科学状态，减少在多个页面之间来回比对。
3. 在 `/review/tasks` 内建立首页 molecule-object 的专项队列。队列是已有 Paper
   任务的投影，不引入第二个任务、审批或发布流程。
4. 用 Paper 级完成确认作为 Reviewer 提交和 Admin 批准的硬门槛；对外只展示
   Paper/Release 级验证状态，不在每个对象上重复展示 `verified`。
5. 保持现有 changeset、revision、ReviewTask、Admin approval 和 successor Release
   生命周期，并与 Dashboard 视觉统一改造兼容。

## 2. 当前行为与设计边界

### 2.1 已确认的产品语义

- AI baseline 可以在未人工确认的情况下发布。发布表示数据可被访问，不等于数据
  已被人工核验。
- Reviewer 负责在分配给自己的 Paper 任务中核对事实、来源和科学状态；Admin 负责
  审批 Reviewer 提交的冻结 changeset，并决定是否发布 successor Release。
- Reviewer 和 Admin 都确认后，Paper 在 successor Release 中才进入 Paper-level
  `human_verified`。Admin 已批准但尚未发布时，对外仍显示旧 Release 的状态。
- 一个首页 molecule-object 完成核查，不会让整个 Paper 变成 verified。
- 对象内部仍必须保存科学处置状态和审计证据，例如 OCSR 候选、RDKit 可解析、
  已绑定来源、结构已确认、多组分未解析、来源不一致、已拒绝或不适用。这些是
  科学状态，不是重复的“对象已验证”徽章。

### 2.2 不在本设计中改变的内容

- 不改变现有角色模型：Visitor、Reviewer、Admin。
- 不新增顶层导航入口，不新增独立 molecule-review 任务系统。
- 不把 proposal 数组塞入 Visual Object snapshot，也不以客户端状态代替 revision
  或 changeset。
- 不向浏览器暴露源文件系统绝对路径；所有 PDF、crop 和 RDKit 图都通过受保护的
  asset ID 或短期 URL 访问。
- 不用 JSON 编辑器作为正常 Reviewer 入口。必要的原始技术快照只能放在 Admin
  或 debug disclosure 中，并且为只读。
- 不在本轮重新设计 Dashboard，也不改变已经批准的 Dashboard/LeadTrace 视觉 token。

## 3. 产品原则

### 3.1 一个 Paper 一条审核主线

所有修改都属于分配给 Paper 的 ReviewTask 和其 changeset。Region、Visual Object、
MoleculeProposal、Structure、Evidence 等只是同一 changeset 中的不同 revisioned
object。队列、工作台、Diff、Reviewer 提交、Admin 审批和 Release 发布必须回到同一
条主线，避免产生无法解释的双重状态。

### 3.2 先证据，后结论

界面优先呈现 Reviewer 做判断所需的证据：原始页面、聚焦 crop、来源定位、机器
proposal、RDKit 解析结果、已发布版本和当前草稿。结论通过明确的科学状态与理由
表达，而不是只用一个颜色徽章。

### 3.3 Paper 级验证，对象级处置

对象级状态服务于完整性检查、队列排序、结构发布和审计；Paper-level attestation
服务于“这篇 Paper 是否已由 Reviewer 全量核查并由 Admin 认可”。对外用户只需要看到
Paper/Release 级状态，避免在每个对象上制造大量相同的 verified 标签。

### 3.4 减少跨页面记忆

点击队列、Paper 详情中的对象或 Diff 中的修改，都应进入同一个 changeset 工作台，
并自动定位到 page、region、visual object 或 proposal。返回列表后保留筛选、分页和
当前焦点。

### 3.5 固定的信息阅读顺序

每一个工作区都按下面的顺序组织信息，避免身份、证据、结论和流程状态混成一组徽章：

1. **Identity**：当前 Paper、page、object/proposal/structure 是什么。
2. **Evidence**：PDF、crop、source locator、机器输出、RDKit validation 和历史版本。
3. **Scientific decision**：Reviewer 选择的类型、SMILES、binding、disposition、状态
   与理由。
4. **Workflow**：autosave、changeset state、blocker、attestation、Admin decision 和
   Release publication。

身份信息固定在左侧和标题区；证据占据中央最大面积；结论只在右侧 typed inspector
编辑；流程状态固定在底栏。滚动长 inspector 时，Paper 身份、证据画布和提交状态不会
一起消失。

## 4. 选择的架构

```text
AI baseline Release（可发布，未人工核验）
        |
        v
Admin 分配 Paper ReviewTask
        |
        v
Reviewer Paper Workspace
  PDF / Regions
  Visual Objects
  OCSR Proposals
  Structures / RDKit
  Evidence / Activity / Lineage
  Paper 完整性与完成确认
        |
        v
Reviewer 提交带 Paper attestation 的冻结 changeset
        |
        v
Admin 审批（approved, pending publication）
        |
        v
发布 successor Release
        |
        v
Paper 在新 Release 中成为 human-verified
```

### 4.1 选择专用 Paper Workspace，而不是继续扩展 JSON 页面

推荐在现有 `ChangesetPage` 生命周期上增加 Paper scientific workspace 聚合读取和
类型化编辑器。现有 Region CRUD/split/duplicate/tombstone、Visual Object binding、
Structure validate/draw/create/update 和 changeset revision 服务作为写入边界继续复用。

不选择以下方案：

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| 在当前 ChangesetPage 中继续给 JSON 文本框加字段 | 不采用 | 上手快，但字段约束、crop/来源上下文、proposal 生命周期和冲突处理会继续混在一起，容易产生不可审计的半结构化数据。 |
| 为 molecule-object 建立独立 ReviewTask/审批/Release | 不采用 | 会出现 Paper 任务和对象任务的双重完成语义，队列也无法可靠回答 Paper 是否完成。 |
| 将 proposal 数组直接写入 Visual Object snapshot | 不采用 | 机器原始输出无法独立版本化，模型重跑、Reviewer 修正和候选比较会互相覆盖。 |
| 只在 Paper 详情补几个链接 | 不采用 | 不能解决 Reviewer 的编辑效率、冲突、完整性和提交门槛问题。 |

## 5. 信息架构

### 5.1 `/review/tasks`：Paper 任务与首页对象队列

页面继续命名为“核查任务”，不增加新的顶层导航。页面由两个同级工作区组成：

1. **Paper 任务**：展示分配给当前 Reviewer 的 Paper、任务状态、优先级、changeset
   状态、Paper 级进度和下一步动作。
2. **首页 molecule-object**：展示这些 Paper 的首页分子对象投影，供 Reviewer 快速
   处理定位、切分和 OCSR 工作；每一行都带回所属 Paper、page、object、changeset
   和当前 scientific state。

首页对象队列的默认分组：

```text
待定位/待切分
待 OCSR
OCSR 待审核
来源或附件待确认
结构组装待确认
已完成（折叠）
```

推荐桌面布局：

```text
┌──────────────────────────────── 核查任务 ────────────────────────────────┐
│ [Paper 任务 12] [首页 molecule-object 48]   搜索…  blocker-only  筛选   │
├──────────────────────────────────────────────────────────────────────────┤
│ 待定位/待切分  6                                                       │
│ [crop] Paper title · p1  OBJ-001  mixed region  缺 Region    进入工作台 │
│ [crop] Paper title · p1  OBJ-004  complete       需拆分       进入工作台 │
├──────────────────────────────────────────────────────────────────────────┤
│ OCSR 待审核  18                                                        │
│ [crop] L22 · 63% min confidence  RDKit 可解析  Paper 进度 31/42  进入…  │
├──────────────────────────────────────────────────────────────────────────┤
│ 已完成 24（默认折叠）                                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

队列行的最小信息：

| 信息 | 用途 |
| --- | --- |
| Paper 标题、Paper ID、页码 | 识别上下文和跳转目标 |
| crop 缩略图 | 不打开工作台即可判断是否为目标区域 |
| object label/type | 判断完整分子、骨架、R 基或混合区域 |
| OCSR 状态、RDKit 状态 | 排序和决定下一步动作 |
| 来源绑定状态 | 识别缺少 source locator 的对象 |
| Paper 进度 | 防止把对象完成误认为 Paper 完成 |
| “进入工作台” | 打开同一 Paper changeset 并 deep-link 到对象 |

筛选项：Paper、page、object type、队列状态、proposal quality、RDKit status、是否
缺少来源、是否有 blocker。排序默认使用 blocker 优先、低置信度优先、页面顺序次之。
“已完成”默认折叠，避免队列被历史结果淹没。

队列是查询投影：同一 object 在 Paper 任务中只有一个审核处置，队列不会创建独立
版本、独立评论线程或独立提交按钮。

队列状态由服务端按以下优先级推导，不由 Reviewer 手工选择。一个对象只出现在最高
优先级的未解决分组中，修复该问题后再进入下一分组：

| 优先级 | 队列状态 | 推导条件 |
| --- | --- | --- |
| 1 | 待定位/待切分 | 缺少有效 Region、Region 越界、混合区域尚未拆分，或 crop 与 page 不一致 |
| 2 | 待 OCSR | 对象类型需要结构识别，但没有可用 proposal，或 inference 失败后尚未处置 |
| 3 | OCSR 待审核 | 存在 `pending` proposal，尚未 accepted/corrected/rejected/not applicable |
| 4 | 来源或附件待确认 | crop asset、source locator、Region/asset/compound binding 缺失或冲突 |
| 5 | 结构组装待确认 | proposal 已处置，但 resulting Structure 缺失、不可解析、多组分未选定或 source mismatch 未处置 |
| 6 | 已完成 | 适用性、来源、proposal 和 Structure 均有合法处置且对象无 blocker |

“已完成”是对象工作已结束的队列状态，不是公开 verification，也不会直接改变 Paper
的 `review_status`。

### 5.2 `/review/changesets/:changesetId`：Paper Workspace

工作台保留当前 changeset 路由，并把原有编辑、Diff、Submit 组织为以下视图：

```text
概览 | PDF 与 Regions | Molecule Objects | OCSR 与 Structures | 科学数据 | Diff | 提交
```

默认打开“概览”或队列指定的 deep-link 视图。Reviewer 只能在 draft 或 revised draft
状态编辑；submitted、approved、published 等状态切换到只读证据模式。

### 5.3 Paper 详情

公开 Paper 详情继续以当前 Release 为边界，新增或补回以下信息：

- Paper-level verification badge 与简短定义，例如“AI 提取基线 / 未经人工核验”、
  “人工核验数据集 / 已核验”。
- Paper 完成度摘要：对象总数、已处理、阻塞项、来源缺失和结构待确认数量。摘要
  来自已发布 Release 快照，不从当前数据库的未发布草稿实时推断。
- 代表性 PDF page/crop 入口和 source locator。访客只能访问已发布且有权限的 asset。
- 结构图、canonical SMILES、结构科学状态和来源对照；不展示 Reviewer 草稿或内部
  proposal，除非该 proposal 已被发布为 Paper 数据的一部分。
- lineage、evidence 与 visual object 之间的来源跳转，点击后回到对应 page/crop 或
  结构记录。

Reviewer/Admin 的 Paper 详情则使用 workspace 聚合数据，可看到当前 draft、机器
proposal、冲突和内部审计信息。

### 5.4 信息放置规则

完整证据和所有写操作只放在 Reviewer Workspace；Paper 详情保持只读，展示当前
Release 中已经发布的结论与来源。Reviewer/Admin 从 Paper 详情点击“在核查工作台中
打开”时，使用 URL query 恢复精确焦点，例如：

```text
/review/changesets/{id}?view=ocsr&page=1&object={object_id}&proposal={proposal_id}
```

这样既能在 Paper 详情补回 crop、RDKit 图和来源定位，也避免在两个页面同时提供写入
入口。URL 中的 ID 只是定位提示，服务端仍检查它们是否属于当前 Paper、task 和
changeset；无效 deep-link 回退到 Paper 概览并显示原因。

## 6. Reviewer 工作台布局

采用面向重复核查工作的高密度三栏工具布局，而非营销式大卡片：

```text
┌────────────────────┬──────────────────────────────────┬────────────────────────┐
│ Context rail       │ Evidence canvas                  │ Typed inspector        │
│ Paper / page /     │ PDF whole page or focused crop   │ Region / object /       │
│ queue / blockers   │ overlays, proposal and RDKit     │ proposal / structure   │
├────────────────────┴──────────────────────────────────┴────────────────────────┤
│ sticky status/action bar: autosave · blockers · diff · submit eligibility       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 6.1 左侧 Context rail

- Paper 标题、DOI/Paper ID、当前 Release 和 changeset workflow state。
- Paper 级进度：`已处理 / 总范围`，并分别显示 Regions、Objects、Proposals、Structures
  的 blocker 数量。
- page 树：只列有 Region、Visual Object 或 proposal 的页面；当前 page 高亮。
- 当前 page 下的 object 列表，按队列状态排序；完成项可以折叠。
- `上一个未解决`、`下一个未解决` 和返回任务队列操作。
- 过滤器不改变服务端状态，刷新后保留在 URL query 中。

### 6.2 中央 Evidence canvas

- `整页 / 聚焦 crop` 切换；整页用于理解上下文，crop 用于精确辨认结构。
- PDF.js 页面和 Region overlay 共用稳定坐标。拖拽新建、移动、调整和旋转 Region
  时显示归一化边界与 page number。
- 选中 Region 后，相关 Visual Object、crop asset 和 source locator 同步高亮。
- 对有 OCSR 的对象，显示 `crop | machine proposal | reviewed structure` 三列或两列
  对比；RDKit 图固定在稳定的预览框内，图像加载失败时保留 SMILES 和错误提示。
- 结构图与原始 crop 的缩放互不影响；浏览 PDF 时不会因为右侧字段长度变化而跳动。
- 可选“仅看当前对象”聚焦模式，关闭无关 overlay，但不能隐藏来源和状态信息。

### 6.3 右侧 Typed inspector

右侧根据当前选中的实体显示专用编辑器。所有动作都写入当前 changeset，并在保存
状态中给出反馈。

**Region inspector**

- region key、page number、x0/y0/x1/y1、rotation。
- 关联 crop/visual object 数量和 source locator。
- `保存边界`、`复制`、`拆分`、`删除（tombstone）`、`恢复`；危险动作需要确认。
- 边界校验失败时就地指出范围、方向或 page 错误，不生成无效 revision。

**Visual Object inspector**

- object key、对象类型、显示标签。
- Region bindings、asset/crop bindings、compound bindings 和 relation 列表。
- 每个 binding 显示角色、置信度、操作类型以及跳转到 source 的按钮。
- 对象类型选项沿用现有枚举：完整分子、共享骨架、R 基、连接子、可变位点、替换
  片段、多结构区域、反应/方案上下文、混合化学区域、非结构内容、待确认。

**OCSR inspector**

- 只读机器字段：raw SMILES、token confidence、mean/min confidence、inference
  status/error、machine canonical SMILES、model version、generated time、RDKit status。
- 机器诊断：不可解析 token、分隔的多组分、heuristic primary component、proposal
  quality。
- Reviewer 字段：处置为 `pending / accepted / corrected / rejected / not_applicable`、
  reviewed SMILES、选择的 compound、rationale、resulting structure。
- `接受候选`、`编辑并校验`、`拒绝`、`不适用` 四个明确动作。接受和修正都必须经过
  Structure validation；拒绝和不适用必须填写理由。

**Structure inspector**

- 使用现有 `StructureEditor` 的专用输入：SMILES、selected component、experimental
  material、source comparison、source verified、human confirmed、科学状态、source、
  reason。
- 科学状态沿用 `StructureState`：proposal、parseable candidate、source-bound candidate、
  structure confirmed、constitution confirmed、non-unique stereochemistry、
  multicomponent unresolved、source-structure mismatch、rejected。
- 实时显示 RDKit validation 消息、component count、canonical SMILES 和 RDKit drawing。
- 结构图支持与 crop 并排比较；结构确认前必须能回到来源定位。

### 6.4 底部 sticky status/action bar

始终显示：

- 自动保存状态：已载入、等待保存、保存中、已保存、离线本地恢复、冲突、保存失败。
- `N 个 blocker`、`N 个待处理对象` 和 Paper-level completion 状态。
- `查看 Diff`、`恢复冲突`、`保存并继续`、`提交核查`。
- 提交按钮的 disabled 原因，例如“仍有 3 个必需对象未处置”或“缺少 Paper 完成确认”。

### 6.5 Admin 审批模式

Admin 审批复用同一 workspace 的只读模式，不再以 JSON Diff 作为主要判断界面：

- 顶部先显示 Reviewer、任务范围、attestation、提交时间、base Release 和 changeset
  snapshot hash。
- 默认过滤为“仅看变更”和“仅看 blocker/非正常处置”，可切换到完整 Paper scope。
- 中央证据画布保持 PDF/crop/RDKit/source context；右侧以 before/after 显示 Reviewer
  的科学结论和理由。
- Admin 可以将评论锚定到 Region、Object、Proposal、Structure 或具体字段，并执行
  `批准`、`要求修改`、`拒绝`；要求修改/拒绝必须写 reason。
- Admin 批准时重新执行 Paper completeness 和 asset validation。任何失效 source、
  scope hash 漂移或结构 blocker 都禁用批准，并明确给出可定位的原因。
- 批准完成后显示“已批准，待发布”，不能用视觉样式让 Reviewer/Visitor 误以为已经
  进入当前公开 Release。

## 7. 四类核心核查流程

### 7.1 Region 核查

1. Reviewer 从 page 树、队列或 Paper 详情进入指定 page。
2. 工作台载入保护 PDF 和当前 changeset 的 Region revisions，并高亮目标 Region。
3. Reviewer 拖动/调整边界或创建、拆分、复制 Region；客户端只负责交互，服务端
   `RegionService` 负责归一化与版本校验。
4. Reviewer 为 Region 选择或确认 Region key，并检查 page、rotation、crop 结果。
5. 保存后生成 visual_region revision；冲突时显示服务端版本和本地版本，禁止静默覆盖。
6. 如果 Region 关联的 object/crop 受到影响，左侧 blocker 会重新计算，直到相关对象
   重新确认。

### 7.2 Visual Object 核查

1. Reviewer 选中 Region 中的 object，右侧加载 object identity 和所有 bindings。
2. 使用 select、create、update、remove 操作编辑 Region、asset、compound binding；
   不需要拼 JSON。
3. 修改对象类型或 label 后显示变更 Diff；删除 binding 默认是 changeset 中的 remove，
   不直接物理删除历史记录。
4. 对混合区域，先在 object 层标记 `mixed_chemical_region` 或拆分为多个对象，再
   进入各自的 OCSR 流程。
5. 没有可解释来源的对象不能标记为结构 confirmed；可以保存为 pending、rejected 或
   not applicable，但必须填写理由。

### 7.3 OCSR Proposal 核查

1. 从首页 molecule-object 队列或对象 inspector 进入 proposal。
2. 中央区域同时显示 crop、机器 SMILES/RDKit 结果和来源 page；低置信度 token 在
   诊断区标出，不在 PDF 上覆盖不可读的长文本。
3. Reviewer 选择接受、修正、拒绝或不适用。
4. 接受：保留 raw proposal，调用 Structure validation，产生 reviewed SMILES 并绑定
   到已有或新建 Structure。
5. 修正：通过 StructureEditor 输入，实时验证；保存 reviewed SMILES、source comparison、
   reason 和 resulting structure。
6. 拒绝/不适用：proposal 仍保留为机器证据，写入 disposition 和 rationale，不把 raw
   SMILES 当成已确认结构发布。
7. OCSR 处置完成后，相关 Visual Object 的队列状态更新；只有 Paper-level blocker
   全部清零时才允许提交整篇 Paper。

### 7.4 Structure 核查

1. 从 proposal、compound 或结构列表进入 Structure inspector。
2. 先确认来源和 component，再确认 RDKit 可解析性；结构图只是辅助证据，不能替代
   source locator。
3. 对多组分结构必须明确选择 primary component 或标记
   `multicomponent_unresolved`，不能隐式丢弃组分。
4. 对来源与结构不一致，使用 `source_structure_mismatch` 并填写比较结果；不能用
   `structure_confirmed` 绕过 mismatch blocker。
5. 结构状态、canonical SMILES、drawing asset 和 source/reason 一起形成 revision。

### 7.5 Paper 完成确认与提交

Reviewer 点击“提交核查”前，系统生成当前 Paper 的 frozen review scope：

- scope 中所有 required Paper/Region/Object/Proposal/Structure/Evidence/Activity/Lineage
  item 都被纳入完整性计算；有 blocker、有修改或有机器 proposal 的 item 必须有显式
  处置；无 blocker 且保持 base revision 的 item 由 Paper attestation 统一覆盖，不要求
  Reviewer 给每个对象重复点击“已验证”；
- 所有 blocking 状态已经解决，或被明确标为允许发布的非阻断状态；
- 必须结构有合法 StructureState 和 source/reason；
- proposal 的 raw machine evidence 没有被 reviewed 字段覆盖；
- Paper revision 的 `normalized_values.review_status` 为 `reviewed`；
- Reviewer 明确勾选 Paper-level completion attestation，并确认“我已核查此 Paper
  当前 scope 中的全部必需内容”。

“确认全文核查完成”由专用服务执行：先验证 frozen scope 和 blocker，再原子地写入
attestation，并创建或更新 Paper draft revision 的 `review_status=reviewed`。Reviewer
不能在普通字段编辑器中直接修改这个状态。确认后若 Region、Object、Proposal、
Structure 或其他 required item 再次发生 mutation，旧 attestation 立即变为 stale，
提交前必须重新确认。

系统将 scope hash、blocker 计数、item 计数、Reviewer ID、时间和 attestation 文本
写入 changeset 的提交快照。提交后 scope 不再随数据库新对象变化而漂移。

## 8. 首页 molecule-object 数据与 `MoleculeProposal` 模型

### 8.1 导入与标识

现有导入已经把 `first_page_molecule_objects.csv` 作为 `visual_object`，而
`first_page_molecule_proposals.csv` 中还包含 OCSR 所需的机器字段。设计新增一类
独立的 `molecule_proposal` revisioned record（具体表名可为
`molecule_proposals`），与 Visual Object 和 Paper 建立明确关系。

实现时扩展 `ObjectKind` 增加 `MOLECULE_PROPOSAL = "molecule_proposal"`，并同步
changeset schema、revision validation、Release manifest/export/import、diff 分类和
审批投影。它与其他 revisioned object 一样进入 frozen scope，但不会替代 Visual
Object 或 Structure identity。

稳定身份建议由以下组合确定：

```text
(paper_id, visual_object_id, proposal_key, model_run_id/model_version)
```

模型重跑产生新的 proposal revision 或新的 model run，不覆盖旧机器证据。proposal
必须能追溯到导入 candidate、crop asset 和产生它的模型版本。

proposal 必须被一个不可变 Release manifest 固定。如果 AI baseline candidate 尚未
发布，proposal 与 Visual Object 一起进入同一个 baseline Release；如果 baseline 已经
发布，回填时不得修改历史 manifest，而应先创建一个只增加 machine evidence 的
successor Release。这个补录 Release 仍是 `unverified`，不会因为加入 proposal 被误标
为人工核验。新 ReviewTask 基于补录后的 Release；已经开始的 changeset 继续使用旧
base scope，或由 Admin 明确 supersede 后重建，不能自动换基线或静默插入新 proposal。

### 8.2 不可变机器字段

- `paper_id`、`visual_object_id`、`proposal_key`、candidate/model run ID。
- 受保护的 crop asset ID、page number 和 source locator reference。
- `raw_smiles`。
- `token_confidences`、`mean_token_confidence`、`min_token_confidence`。
- `inference_status`、`inference_error`。
- `rdkit_status`、`machine_canonical_smiles`、`heuristic_primary_component_smiles`。
- `model_version`、`proposal_quality`、`generated_at`、导入来源和内容 hash。

### 8.3 可修订 Reviewer 字段

- `disposition`：`pending`、`accepted`、`corrected`、`rejected`、`not_applicable`。
- `reviewed_smiles`、`selected_component_smiles`。
- `rationale`、`source_comparison`、`source_verified`。
- `compound_id`、`resulting_structure_id`、`reviewer_id`、`reviewed_at`。
- 当前 changeset/revision/workflow state。

接受或修正 proposal 时，reviewed 字段通过现有 Structure validation 和 Structure
create/update 服务写入；proposal 本身只保存处置与关联，不复制一套结构验证规则。

### 8.4 Crop 和路径安全

CSV 中的绝对 `crop_path` 只作为导入源元数据，进入应用后转换为 managed asset ID。
API 返回：

- asset ID、filename、width、height、sha256；
- 当前用户可用的短期预览 URL；
- source locator 的 page/region/object 坐标。

API 不返回 `/data/home/...` 等服务器路径，也不允许客户端自行拼接路径。

## 9. 读写 API 契约

以下为设计契约，具体 URL 可在实现阶段与当前 router 命名保持一致。读接口优先提供
一个聚合响应，避免页面并行请求后出现不同 changeset version 的拼接状态。

### 9.1 Workspace 聚合读取

```http
GET /api/v1/review/changesets/{changeset_id}/workspace
```

返回：

```json
{
  "changeset": { "id": "...", "version": 12, "workflow_state": "draft" },
  "paper": { "id": "...", "title": "...", "base_release_id": "..." },
  "progress": {
    "scope_count": 42,
    "resolved_count": 39,
    "blocker_count": 3,
    "by_kind": { "visual_region": {}, "visual_object": {}, "molecule_proposal": {}, "structure": {} }
  },
  "pages": [],
  "regions": [],
  "visual_objects": [],
  "molecule_proposals": [],
  "structures": [],
  "evidence": [],
  "attestation": null,
  "assets": [],
  "source_locators": []
}
```

聚合响应带 `workspace_version` 或等价的 changeset version。所有 mutation 都必须
带 `expected_version`，返回更新后的 changeset version 和受影响 entity。

### 9.2 首页对象队列读取

```http
GET /api/v1/review/tasks/first-page-molecule-objects
```

查询参数：`status`、`paper_id`、`page`、`object_type`、`has_blocker`、`cursor`、`limit`。

返回的每行包含 `paper_id`、`review_task_id`、`changeset_id`（若已创建）、object/crop
摘要、proposal 状态、Paper progress 和 deep-link 参数。没有 changeset 时，点击行
先进入现有“开始核查”流程，再定位对象；不会静默创建第二条任务。

### 9.3 Region 与 Visual Object mutation

继续使用现有 Paper-scoped router 和 `changeset_id + expected_version`：

- `POST/PATCH /api/v1/papers/{paper_id}/regions...`
- `POST /regions/{region_id}/duplicate|split|tombstone|restore`
- `GET/POST/PATCH /api/v1/papers/{paper_id}/visual-objects...`
- binding 的 create/update/delete 继续由 Visual Object router 处理。

前端 typed client 负责把控件值转换为服务端请求；workspace 不允许直接提交任意 JSON
字段。

### 9.4 Structure 与 OCSR mutation

继续复用：

- `POST /api/v1/papers/{paper_id}/structures/validate`
- `POST /api/v1/papers/{paper_id}/structures/drawings`
- `POST/PATCH /api/v1/papers/{paper_id}/structures...`

新增 proposal 读写建议：

```http
GET   /api/v1/papers/{paper_id}/molecule-proposals
PATCH /api/v1/papers/{paper_id}/molecule-proposals/{proposal_id}
```

PATCH 只接收 typed 字段：`expected_version`、`disposition`、`reviewed_smiles`、
`selected_component_smiles`、`compound_id`、`resulting_structure_id`、`rationale`、
`source_comparison`、`source_verified`。接受/修正操作在服务端调用结构验证；raw machine
字段不可写。

### 9.5 Paper-level attestation

```http
POST /api/v1/review/changesets/{changeset_id}/attestation
```

请求：`expected_version`、`scope_hash`、`statement`、`confirmed=true`。

提交 endpoint 在服务端重新读取 frozen scope 并验证 blocker、item completeness、
Paper revision 和 attestation；客户端的 `submit eligible` 仅是提前反馈，不能替代
服务端门槛。

## 10. Paper 完整性与 Verification 计算

### 10.1 Frozen review scope

创建或首次打开 changeset 时记录 base Release 的 Paper scope。scope 至少包含：

- Paper revision；
- base Release 中的所有可审核 Region、Visual Object、Structure、Evidence、Activity、
  Lineage 和 required MoleculeProposal；
- 被队列标记为 blocker 的首页 molecule-object。

在 Reviewer 工作期间新导入的候选不会自动混入已提交的 scope；Admin 必须重新打开
任务或创建新 changeset。这样可以保证 Reviewer 的“全量核查”有固定分母。

### 10.2 提交门槛

服务器将当前至少一个 item 的旧门槛替换为以下规则：

- required scope 中所有有 blocker、有变更或有 proposal 的 item 都有显式 disposition；
- 无 blocker、无变更的 base item 被当前 scope hash 和 Paper attestation 覆盖，不需要
  单独保存一个对象级 verified 标记；
- blocker 为 0；
- 所有需要 source 的 item 有 source locator 或明确的 rejected/not_applicable 理由；
- 所有 Structure item 通过相应的科学状态校验；
- Paper revision 的 `review_status=reviewed`；
- attestation 的 `scope_hash` 与当前 frozen scope 一致，且 attestation 没有因后续
  mutation 变为 stale。

对于确实不适用的对象，`not_applicable` 是可审计处置，不等于遗漏；界面必须要求
理由，并在 Diff 和 Admin 审批摘要中可见。

### 10.3 Admin 审批与 Release 发布

Admin approve 前重新验证：changeset snapshot hash、scope hash、attestation、所有
required item、binding delta、Structure validation 结果和 asset 可用性。审批成功后
ReviewTask 可进入 completed，但 Paper 的公开 verification 仍等待 successor Release
发布。

发布 successor Release 时，禁止 `_metrics_with_operation()` 直接复制旧的 `human_review`
计数。发布服务必须从该 Release 的 frozen Paper revisions/review attestations 重新
计算：

```text
human_review.denominator = 本 Release 中的 Paper 数
human_review.numerator   = 有有效 Reviewer attestation 且 Admin approved 的 Paper 数
```

并保留 `scope_count`、`resolved_count`、`blocker_count` 等质量指标用于诊断。历史
Release 的指标和 verification_status 不被回写。

### 10.4 对外状态展示

Release 级状态仍为：

```text
0/N       -> unverified
1..N-1/N  -> partially_verified
N/N       -> human_verified
```

Paper 详情显示该 Paper 在当前 Release 的状态。对象列表只显示科学状态和来源状态，
不显示重复的 `对象已验证`。Admin 可额外看到 `approved, pending publication`，访客看
不到未发布 successor Release。

## 11. 权限、审计与安全

- Visitor：只能读当前已发布 Release 允许公开的 Paper、asset、结构和来源信息；不能
  访问草稿、proposal raw diagnostics、changeset 或服务器路径。
- Reviewer：只能读写分配给自己的 Paper draft；必须通过 CSRF、expected_version 和
  当前 ReviewTask 归属检查；不能审批或发布。
- Admin：可以查看所有任务、草稿和候选，执行分配、reassign、approve、publish 和
  debug read-only snapshot。
- 所有 proposal disposition、Region 操作、binding 变化、Structure 状态变化、
  attestation、submit、approve、publish 都写入服务端审计记录，包含 actor、Paper、
  changeset、old/new state、reason、request ID。
- crop/PDF/RDKit asset 使用受保护的 asset endpoint 和短期 URL；source locator 只返回
  page、region、object 等应用语义，不返回本地绝对路径。
- 评论 anchor 必须与当前 object/revision 绑定；删除对象使用 tombstone，保留历史。

## 12. 保存、冲突与异常状态

### 12.1 Autosave

- 字段编辑采用短延迟 debounce；每次 mutation 都携带 changeset version。
- 保存成功后更新本地 version、Diff 和 blocker 计数；离线时保留本地 recovery，明确
  显示“未写入服务端”。
- 关闭或切换 Paper 前若有 pending save，先等待、取消或明确提示，不静默丢弃。

### 12.2 并发冲突

- 409/`REVISION_CONFLICT` 显示服务端值、本地值、最后修改人和时间。
- 对简单字段可提供逐字段选择；Region geometry、proposal disposition + reviewed
  SMILES、Structure state 等科学字段默认要求 Reviewer 显式选择，不自动合并。
- 冲突解决后重新运行 validation 和 Paper completeness；未解决冲突禁止提交。

### 12.3 加载、空数据与错误

- 聚合加载显示 page/object/proposal 的 skeleton，不让三栏因异步数据到达顺序跳动。
- Paper 没有首页 molecule-object 时显示“该 Paper 无首页分子对象”，不创建空任务。
- 没有 crop、PDF 或 RDKit 图时保留 metadata、SMILES、source locator 和可复制的错误
  信息；不显示破损图片占位符冒充证据。
- API 失败显示 request ID、可重试按钮和当前本地草稿状态；不会把失败的 mutation
  标成已保存。

## 13. 响应式、可访问性与视觉约束

### 13.1 布局断点

- 桌面端优先：左 rail 260-300px，中间 canvas 使用剩余空间，右 inspector 340-420px；
  PDF/crop 预览使用固定最小高度和 `aspect-ratio`，避免内容改变导致布局跳动。
- 平板：保留 canvas + 一个可折叠 inspector，Context rail 变为抽屉或顶部对象条。
- 手机：以队列、来源和只读信息为主；编辑器按单列显示。精确 Region 绘制在可用宽度
  不足时禁用并提示转到桌面端，不提供难以操作的伪精确交互。

### 13.2 Dashboard 对齐

- 使用已批准的 `tokens.css`、`base.css`、`components.css`、`layouts.css`；页面级样式
  只保留 PDF overlay、crop geometry、RDKit preview 和 lineage geometry。
- 采用米白纸张背景、深蓝导航、珊瑚主动作、青绿完成、琥珀待处理、红色危险；面板
  细边框、小圆角、紧凑留白，避免“大圆角卡片套卡片”。
- 工作台的信息密度高于公开首页，但字体、状态色、按钮、焦点和反馈组件必须复用
  全局 token。

### 13.3 键盘与屏幕阅读器

- Region/object/proposal 列表支持上下移动、Enter 聚焦、`N/P` 跳到下/上一个未解决项；
  快捷键不覆盖文本输入。
- 所有 canvas 控件、缩放、旋转、切换视图都有可访问名称；不能只依赖颜色区分状态。
- 自动保存、validation、冲突和提交资格通过 `aria-live` 提示；焦点在视图切换后移到
  新面板标题或目标对象。
- 支持 `prefers-reduced-motion`，图片与 PDF 加载失败时仍有等价文本证据。

## 14. 测试与验收标准

### 14.1 后端

- Workspace 聚合返回同一 changeset version，并拒绝不属于当前 Paper/task 的对象。
- Region create/update/split/duplicate/tombstone/restore 的 bounds、rotation、
  expected_version 和审计事件测试。
- Visual Object binding 的新增、修改、删除和 tombstone 测试。
- MoleculeProposal raw machine 字段不可写；接受/修正调用 Structure validation；拒绝/
  不适用必须有理由；模型重跑不覆盖旧 proposal。
- frozen scope、scope hash、Paper revision `review_status=reviewed`、attestation 和
  blocker 门槛测试；空 changeset、单对象 changeset 和 scope 漂移必须被拒绝。
- Admin approval 与 successor Release 发布重新计算 `human_review`，不复制旧指标；
  historical Release 不变。
- Reviewer/Visitor/Admin 权限、CSRF、asset path 隔离、request ID 和并发冲突测试。

### 14.2 前端

- `/review/tasks` 的 Paper 任务和首页对象队列使用同一 changeset deep-link；筛选、分组、
  分页和返回状态保持。
- `ScientificEditors` 对 Region、Visual Object、OCSR、Structure 显示专用控件，正常
  Reviewer 路径不渲染 JSON textarea。
- PDF/crop/OCSR/RDKit/source locator 同步选中，加载失败和空状态有等价文本。
- 类型化字段更新、autosave、409 冲突恢复、离线 recovery、submit eligibility 和
  attestation 流程测试。
- Paper 详情只显示当前 Release 的 Paper/Release verification，不出现对象级 verified
  重复标签；Admin 的 pending publication 状态不泄漏给 Visitor。

### 14.3 验收走查

```text
Admin 登录
-> 确认 AI baseline 可发布但未核验
-> 分配一个 Paper
-> Reviewer 从首页对象队列进入同一 Paper changeset
-> 调整 Region，确认 crop/source locator
-> 接受或修正 OCSR，查看 RDKit 图和 Structure state
-> 完成所有 required scope 并提交 Paper attestation
-> Admin 审批
-> 发布 successor Release
-> Visitor 看到 Paper/Release human-verified，且对象无重复 verified 徽章
```

## 15. 迁移与发布顺序

1. **前置依赖**：先完成并合并 `codex/leadtrace-dashboard-styles` 的视觉统一工作，
   以稳定的全局 token 和 layout class 作为工作台基础。新工作台不得在页面中重新定义
   通用按钮、面板、表格或状态颜色。
2. **数据准备**：为已导入的 `first_page_molecule_proposals.csv` 建立
   MoleculeProposal 记录，保留 candidate、crop asset、model version 和 content hash；
   导入失败的行进入可审计错误队列。
3. **后端先行**：实现 workspace aggregate、proposal record/endpoint、frozen scope、
   attestation 和 Release metrics recomputation；先用 API/服务测试锁定门槛。
4. **Reviewer 工作台**：将 `ScientificEditors` 扩展为 typed editors，接入 PDF/crop/
   RDKit/source context；保留现有 changeset autosave/recovery/conflict 机制。
5. **任务队列**：在 `/review/tasks` 增加首页 molecule-object projection 和 deep-link，
   不新增顶层菜单或独立审批动作。
6. **Paper 详情**：补回公开 Release 中可用的 crop、source locator、结构图和 Paper-level
   quality summary；按权限隐藏 draft/proposal diagnostics。
7. **灰度与回滚**：先为 Reviewer/Admin 开启 workspace feature flag；旧 ChangesetPage
   只作为受限 fallback，不允许新旧页面同时写入同一实体；验证通过后移除 JSON 主入口，
   只保留 Admin/debug 只读快照。

## 16. 非目标与后续候选

本阶段不做：

- 新的 OCSR 模型训练、主动学习平台或批量重推理控制台；
- 逐 token 的图像标注工具；token confidence 先作为诊断信息展示；
- Visitor 侧的对象级人工评论或对象级 verified 筛选；
- 跨 Paper 的批量科学修改；
- 以手机为主要输入设备的精确 PDF 几何编辑。

后续可评估：批量接受高置信度 proposal、Reviewer 协作锁、模型版本 A/B 对比、来源
定位的全文检索和基于历史处置的队列优先级学习。但这些功能必须继续复用 Paper task、
changeset、attestation 和 Release 语义。

## 17. 需要确认的事项

本文件已采用当前讨论中确认的产品方向。开始生成实现计划前，请确认以下内容：

- `MoleculeProposal` 作为独立 revisioned record，而不是 Visual Object snapshot 的嵌套数组；
- 首页 molecule-object 队列放在 `/review/tasks`，并且只是已有 Paper 任务的投影；
- Reviewer/Admin 通过 Paper-level attestation 判定完成，对外不展示对象级 verified 徽章；
- changeset 提交必须满足 frozen scope 全量处置、blocker 清零和 Paper `review_status=reviewed`；
- successor Release 发布时重新计算 Paper-level `human_review` 指标；
- 先合并 Dashboard visual-alignment 分支，再实现本工作台。

确认后，下一步单独生成实现计划，按后端数据/API、前端工作台、任务队列、Paper 详情、
测试与灰度发布拆分任务；在确认前不修改业务代码。
