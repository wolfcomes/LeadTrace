# Activity、原文结构截图与可选 Edge Evidence 验收

用户反馈：预览缺 Activity 与分子结构原文截图；AI 判断存在的 Edge 应允许没有文本 Evidence。

## 根因与改动

- 旧 `compound_activities.csv` 有 620 条其他论文记录，但不含此次四篇。此前适配器输出 Activity=0，并非数据库或页面漏显示。
- 旧适配器固定返回空 `structure_locators`，所以此前只看到 RDKit 重绘，没有原文截图。
- 底层 Candidate/Lineage API 支持无 Evidence Edge，但历史适配器要求每条边至少有可用文本 Evidence；提交检查还要求已确认边必须有关联 Evidence。这两处门槛已取消。
- 端点已确认结构、明确关系状态、人工否定和自环检查保留。无支持 Evidence 的 Edge 返回非阻断 `needs_review`，应用后仍是 AI draft；审核员仍需确认关系或明确未解决状态。
- Activity 提供页顶直达入口、化合物筛选和每页 25 条分页；已有 entity 链接能自动定位所在页，新增/编辑/删除行为保留。005 的 307 个唯一记录 ID 已逐页验证（13 页），筛选后 7 条、最后一条 deep link 均通过。
- 分子原图卡片现在显示 `source_context` 并提供“查看原图大图”，明确区分共享骨架/取代定义与独立完整结构。

## 补提取内容

| Paper | 新 Activity | 有测量值的化合物 | 原文截图定位 | 独立原图 / 共享骨架 |
| --- | ---: | ---: | ---: | ---: |
| 004 | 35 | 6 / 11 | 11 | 4 / 7 |
| 005 | 307 | 41 / 41 | 41 | 2 / 39 |
| 010 | 24 | 6 / 6 | 6 | 2 / 4 |
| 013 | 10 | 10 / 10 | 10 | 0 / 10 |
| 合计 | 376 | 63 / 68 | 68 | 8 / 60 |

- 新增 63 条表格 Evidence，均来自实际 PDF 页码和 bbox，`quoted_text=null`，caption 明示为转录说明，不伪装连续原文引用。
- Activity 保留 assay、endpoint、operator、原文单位、实验条件和原始单元格；SD 放入 context。005/010 的 331 个数值额外按 PDF glyph 行列坐标复核；004/013 的 45 个数值视觉核对图像表格。
- 原文 `nd` 未转成 0。004 的 13 在 10 μM hPKG-I counter-screen 中报告 −4%（SD 2），保留实际结果。
- 004 的 `10g`、`11a`、`11g`、`58`、`61` 未定位到主文 SAR 表的对应活性测量值，明确记录缺口。本轮只补现有 68 个化合物，不宣称穷尽论文或补充材料全部实验。
- 22 组原文裁剪关联到 68 个化合物；60 项为共享骨架加取代定义，8 项独立原图。所有最终边界已逐组视觉复查；与 SMILES 的科学一致性仍须人工审核。
- 放宽 Evidence 后重新检查四篇历史关系，并没有额外符合端点/关系条件的边，仍为 54 条。真实数据库回归验证无 Evidence 的新 AI Edge 可以入库并显示推断理由。

## 实例和证据

外部实验根目录：`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/ai-prefill-preview-20260920.C191Fl`。

新版实例：`7a1f3f21-3c30-4647-b4b9-a8dbbec8c773`，内部 origin `http://127.74.2.3:18080`；已切换并核验局域网入口 `http://10.21.53.251:18080/review/tasks`。原账号密码通过认证密码修改 API 在新实例中保留。旧实例和其候选、反馈、快照保留。

四篇初次应用均 `committed`，Workspace version 2；此前页面备注经实际 Workspace 导出进入新候选，未覆盖原实例。

浏览器对照发现 004 的 `11a`：原文 Scheme 2 标为 N-Boc，旧 SMILES 为 N-Cbz。已通过认证 Reviewer API 在 source_context 添加明确的待审核差异说明，未修改 SMILES。该操作令 004 Workspace 为 version 3，其 receipt 校验为 `changed_since_apply`，符合预期；其余三篇仍 version 2 / `committed`。新增 Evaluation `enriched-v3-004-structure-discrepancy` 绑定该版本，仍 `needs_revision`。旧版 backend 已停止，但数据库及候选/反馈保留。

- `v3-instance.json` / `v3-candidates.json` / `v3-applications.json`：新版身份、候选与应用凭据。
- `v3-evaluation-*.json` / `v3-verification.json`：绑定新版快照的技术检查，仍 `needs_revision`，不声称人工科学审核完成。
- `enrichment/activities.json` / `extract_activities.py` / `activity-verification.json`：活性提取及核验。
- `enrichment/structure_locators.json` / `structure_extract.py` / `structure_locator_review.json` / `structure_crops/`：原图与裁剪依据。
- `enrichment/preserved-baselines.json` / `v2-v3-diff.json`：原 Workspace 保存与新版差异。
- `enrichment/backend-tests.log`：92 passed in 154.68s；涵盖 adapter/worker、validator、apply/Preview HTTP、Lineage API、submission、历史四篇兼容。
- 前端最终 95 项测试、typecheck/build 通过。原图说明与大图入口先确认失败测试，再实现并复验。
- `enrichment/current-preview-verification.json`：最终 LAN 身份、健康检查、两个原账号登录、四篇计数与 receipt 状态。
- `enrichment/browser-lan-v3/verification.json`：实际局域网浏览器逐字段核验全部 376 条 Activity，解码全部 68 张 PNG，验证分页/筛选/原图说明/大图链接；无科学写请求，Workspace 版本前后不变。
- `enrichment/activity-pagination-verification.json`：005 全 13 页记录无遗漏及 deep link 验收。
- 独立只读代码审阅未发现新增 P1/P2；额外 16 项纯校验/adapter 测试通过。

本轮只在隔离 Preview 操作；未改生产数据库或执行生产迁移/预填。旧生产专用四篇脚本仍保留其历史 Evidence 约束，新 Preview 不使用该脚本的 apply/validate 入口。
