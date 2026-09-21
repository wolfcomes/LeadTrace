# PfPKG 004 化合物漏填修复

用户指出《Structure–Activity Relationship of a Pyrrole Based Series of PfPKG Inhibitors as Anti-Malarials》存在大量 Compound 漏填。论文 DOI：10.1021/acs.jmedchem.3c01795。

## 根因与修复范围

漏填来自提取范围，非前端分页。旧候选含 11 个化合物，前次 Activity/截图补充只处理已有标签，没有对照原文独立清单验收。原文 PDF 第 9–12 页的 Tables 1–5 去重后共有 39 个受测化合物，旧候选只包含其中 6 个；另 5 个是中间体。此前的“页面记录与候选相符”检查不能证明原文覆盖完整。

独立原文清单为 [compound-inventory-pfpkg-004.json](examples/compound-inventory-pfpkg-004.json)，每项有标签、源定位和角色。重复对照 1 只计一次，50–53 独立计数。Table 6 的 50–53 已在 39 个受测身份中。

| 指标 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 主表受测身份覆盖 | 6 / 39 | 39 / 39 |
| 工作区 Compound 总数 | 11 | 44 |
| Activity（含 ADME） | 35 | 279 |
| 原图定位 | 11 | 44 |

新增的 33 个标签：1、12c、12d、16、17、18a、18b、19a、19b、20、21、22、23、24、25、26、27、28、32、38、39、40、41、55、56、57、50、51、52、53、12e、12f、54。

本次修复明确覆盖全部主表受测化合物。Figure 1 的其他背景参考药、合成图/Experimental 的额外中间体和起始原料仍不声称全部入库。DeepSeek 另产生了 133 项的初步全篇清单，但其中名称、角色和部分定位存在错误，不能把该数字当作独立审核通过的科学分母；保留原始调查用于后续逐项审查，不将错误清单批量导入。

## 数据补录与核验

- 新增 33 个结构通过分别解析片段、显式连接原子/键构建，最终带标签重绘与原图/实验命名对照；现有 6 个受测结构与重新构建结果一致。
- 38–41 为外消旋体，保存 V3000 Molfile 的增强 AND 立体组和明确的 cis/trans 描述，未将其宣称为单一对映体。50–53 的绝对构型按原文最终命名和 Table 3 校验。当前 canonical-SMILES 重绘可能只显示混合物一个成员，需结合描述和原图理解。
- 55 的桥头构型经复验修正为原文的 1R,5S 后交付。DeepSeek pilot 对 54 的名称写 thiophen-3-yl，却生成了 2-yl SMILES；该错误 pilot 未用于补录，采用对照原图确认的 3-yl 图。
- 独立转录的 Tables 1–6 共 318 项值、比较符号及 ND 检查通过，包含重复对照行，并非 318 个独立实验。SD、原始单元格和条件保留在 context。Table 6 有 60 个 ADME 测量；共新增 244 条 Activity。
- 一处监督者参考转录将 15b 的 T618Q 值误读为 1390，放大 PDF 确认是 1130；纠正参考清单，保留 DeepSeek 正确转录。源文的 IC50/pIC50 不一致未静默重算，均按原文保存并说明。
- 对照 1 在多个主表重复出现，测量入库一次并注明重复上下文。ND 不写成 0，真实负抑制率保留。
- 每个新增化合物关联自身完整共享表格区域，包含骨架、目标行、取代基定义和脚注。检查了最终实际裁剪区域；共享定位不是独立分子结构图。

## 工作区与审计

仍使用原实例 `7a1f3f21-3c30-4647-b4b9-a8dbbec8c773`、原账号和 LAN 入口。004 原工作区 `27bf4ad2-187d-429c-b18b-3d3cf79c3eba` 从版本 3 增至 391。

整包 AI Prefill 应用不允许覆盖已编辑工作区。本次采用现有版本校验编辑 API 增补，操作日志保留每次返回结果。操作使用 preview-reviewer 登录，属于自动化补录，不代表人类审核；结构保持 draft。Molfile 用接口要求的 structure_editor 输入方式，AI 来源和外消旋语义写入描述。

先保存了全部七篇的快照。修复后逐条比对原有科学记录和 ID，004 的原 11 个 Compound、35 个 Activity、11 个定位及既有关系等均保留，原 11a 的 N-Boc/N-Cbz 差异注释也保留。其余六篇快照 hash 完全不变。旧 004 应用回执显示 changed_since_apply 是预期结果；本次没有伪造新的整包应用回执。

首次增补在外消旋 Molfile 使用 ai_prefill 输入方式时被 API 拒绝，之后按 journal 和精确工作区版本恢复，用 structure_editor 正确提交，未重复创建 Compound。新增定位/Evidence 上本次自加的冗余 reviewer_note 无法由 Candidate v1 导出，已通过编辑 API 去除该重复字段；相同说明仍在 source_context/caption，操作历史保留。原有审核者注释未修改。

## 防止复发的工具修复

新增离线命令：

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate coverage candidate.json \
  --inventory compound-inventory.json
```

它比较独立审核的原文标签清单与候选，报告缺失、歧义、额外标签、明确排除项及候选/清单 hash。缺少必填项或匹配歧义退出 4；源身份不一致、重复别名、空清单、未填审核者等输入问题退出 2。旧候选实际报告 6/39、缺少 33 项；新候选及工作区导出均为 39/39。

该检查已加入提取指南、运行指南、提示词和 CLI 文档；监督流程必须运行它。它不自动强制到现有 apply API，也不根据标签匹配宣称科学准确。完整性只针对清单明示的范围；omissions 不会自动豁免 required 标签。

测试先复现缺少 coverage 命令的失败，随后实现。相关 CLI、覆盖检查和原验证回归共 32 项通过，包括此篇实际 33 个漏填的回归用例。

## 证据文件

外部目录：`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/compound-coverage-repair-20260920`。

- `before-workspaces.json`、`004-before.json`、`004-after.json`：完整前后状态。
- `004-main-table-inventory.json`、`coverage-before.json`、`coverage-after.json`：独立分母与覆盖差异。
- `004-main-structures.json`、`build_main_structures.py`、`main-structures-*.png`：结构构建与重绘。
- `004-activities/measurements.json`、`host-source-values.json`、`host-adme-values.json`、`source-value-verification.json`：独立转录和检查。
- `004-host-delivery-review.json`、`004-delivery-candidate.json`、`004-workspace-after-candidate.json`：精确候选放行和实际工作区导出。
- `append-operations.jsonl`、`own-note-normalization.json`、`append-result.json`：实际版本校验增补操作。
- `verification.json`：数据库数量、原内容和其他六篇保留检查。
- `browser/verification.json`、`browser/004-structure.png`、`browser/004-activities.png`：LAN 浏览器验收产物。

两路 harness 首次都遇到 TRANSPORT API 连接错误，保留日志后恢复，第二次均 exit 0。任务成功以实际文件、源文检查、入库和页面验收为准。

最终 LAN Chromium 验收通过：实际 44 个 Compound 行、279 条 Activity 的字段一致性、全部活动分页与筛选、44 张原图解码及大图入口均正常，无页面 JavaScript 错误或验收过程中的科学写请求。数据库检查确认 39/39 主表标签、原有记录逐条保留和其余六篇快照不变。随后重新执行全实例健康及双账号登录检查通过。数据仍为待人工科学复核。
