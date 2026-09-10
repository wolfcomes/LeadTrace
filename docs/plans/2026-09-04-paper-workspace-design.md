# Paper 工作台设计

## 目标

将项目控制台改为 Paper-first 工作台：项目总览只负责显示全局进度，Paper 库按 672 篇 Paper 展开并以每页 20 篇浏览，所有证据、候选记录、显式路径、结构和 OCSR 内容从 Paper 详情进入。

## 信息架构

顶级导航只保留“项目总览”和“Paper 库”。Paper 库是逐篇核查的入口，点击整行进入该 Paper 的独立详情工作台。详情页按“概览、统一复核条目、Paper 审阅”组织内容，保留返回 Paper 库动作和阅读/修改模式。统一复核条目以 candidate 为主，每条同时挂载匹配的 evidence、activity、explicit path、结构和 OCSR；没有 candidate 的 evidence 作为 evidence-only 条目保留。

项目总览继续展示 corpus、text、evidence、candidate、path、structure 和 human review 的分层进度。总览中的待处理项只跳转到 Paper 库并携带 pipeline 或人工 review 筛选，不再打开独立的路径、OCSR 或证据页面。

## 数据与持久化

服务端继续只读加载现有 manifest、text index、evidence、enriched candidates、explicit paths、structure confirmation 和 OCSR proposals。新增 `09_paper_review/paper_review_overrides.json` 作为人工 Paper 修订覆盖层，保存标题覆盖、Paper review status、修订说明、审阅备注和更新时间。该文件只接受 manifest 中已知的 Paper ID，采用临时文件加 `os.replace()` 原子写入，不回写任何原始 CSV、PDF 或自动生成结构结果。

`GET /api/papers` 返回分页 Paper 摘要并合并覆盖层；`GET /api/papers/<paper_id>` 返回 Paper 摘要以及按 `paper_id` 聚合的 `evidence`、`candidates`、`explicit_paths`、`structures`、`proposals` 和 `review_items`；`POST /api/papers/<paper_id>/review` 校验 Paper 字段和状态后保存覆盖层。`POST /api/papers/<paper_id>/review-items/<review_item_id>` 保存一条复核条目的类型化内容、状态和备注草稿；`POST /api/papers/<paper_id>/review-items` 新增人工条目；`DELETE /api/papers/<paper_id>/review-items/<review_item_id>` 删除未确认条目；`POST /api/papers/<paper_id>/review-items/<review_item_id>/confirm` 将条目扁平化写入 `reviewed_entries.csv` 并锁定。已标记 `reviewed` 的 Paper 或条目不允许后续编辑、新增或删除，保持审阅结论稳定。

## 前端行为

阅读模式仅展示数据和原始值。修改模式只为尚未 `reviewed` 的 Paper 展示编辑控件，可直接修改页码、引用、化合物对、报告基团、relation、activity、evidence、路径/结构状态、SI/canonical SMILES 以及审阅备注；保存成功后刷新服务端详情。条目可保存草稿、增删或确认同步；确认后的条目锁定。浏览器 `localStorage` 不再作为 Paper 最终保存位置，所有人工变化进入独立审阅文件，不覆盖服务端源数据。

分子主视觉统一使用 SI SMILES 经 RDKit 生成的图片。文章页截图只标注为来源证据，OCSR crop 只标注为模型输入，DECIMER proposal 不自动升级为最终结构。

## 验证

服务端测试覆盖 672 条稳定 manifest 顺序、20 条分页/34 页/末页 12 条、Paper 详情聚合、review override 读写和 reviewed 锁定；同时保留既有路径、资产安全和结构来源测试。前端使用 `node --check`，服务端使用 `py_compile`，并进行 GET/POST API smoke test。
