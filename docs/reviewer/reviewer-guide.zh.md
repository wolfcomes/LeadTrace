# Reviewer 工作指南

Version: 2026-09-28

> Generated from `leadtrace/frontend/src/review/help/reviewer-guide.json`. Edit that source and run `python leadtrace/ops/reviewer/render_guide.py`.

## 先核对文章与完整覆盖

核对题名、DOI 和 PDF。收录所有有编号或标签且结构可确定的 Compound，包括无活性数据的原料、中间体和对照。示例仅演示格式，不应复制为论文事实。

## Compound 与 Structure

Compound label 保留原文编号（例：24、7a）；显示名称可为空。每个 Compound 维护一个 Structure；SMILES/结构编辑器输入后核对连接、取代位置和立体化学。不能确定时说明原因并明确 unresolved，不虚构结构。

## 文章级研究起点与论文优选

在文章信息页关联本篇 Compound 与已有 Evidence，记录研究起点或论文优选、适用系列/范围及作者选择理由。每类可有多个分子，同一分子可兼任。先在 Evidence 库保存原文依据；标注卡片保留 PDF 页码与原文。研究起点不等于每条合成路线的原料；论文优选不等于所有 terminal 或最低 IC50。待审核、已确认、待解决分别显示，阅读不会自动确认；未记录不代表文章没有此类分子。修改理由、身份或来源后重新核对，需核对提示要显式清除。

## 组织 Lineage

SAR 记录设计和结构比较，synthesis 记录实际合成路线；不要仅凭编号顺序连边。同一逻辑路线的节点属于同一 Lineage；独立路线可分开。root 是路线起点，intermediate 为途中节点，terminal 为路线终点；terminal 不自动表示最佳活性或作者最终候选。作者研究起点与优选分子在文章级标注中记录。孤立对照不必强行连边，在 Compound 描述说明其用途及不入 lineage 的理由。

## 图、Compound、Edge 三个视图

三个页签切换。图上“新增 Node”选择本篇已有 Compound；找不到时先到化合物页创建。“新增 Edge”依次选择起点和终点，再填写关系表单。拖动节点或菱形控制点调整形状，点击“保存布局”；点线图与结构图独立保存。重新载入布局会丢弃该模式未保存的布局。表单仍是完整编辑入口。

## Edge 与 Evidence

关系类型、起终点、修改摘要都要核对。例（虚构格式）：Me → OMe，比较亲脂性变化；该关系由结构比较推断，未见作者明确说明。区分原文支持与推断，不把表格并列当优化顺序。Evidence 保留逐字引文、PDF 实际页码和区域；supports/contradicts/contextual 表示证据作用。阅读不自动把 draft 改为 reviewer_confirmed。

## Activity 格式

例（虚构）：Assay = human MAO-B inhibition；Metric = IC50；Operator = <；Value = 10；Unit = nM；Context 写明测定条件。不要把 <10 nM 全部塞进 Value，不混合不同 assay 的数值。保留原单位与限制条件。

## Abstract 与 PDB

Abstract 保存原文摘要及来源，不使用 AI 总结冒充。PDB ID 支持传统四字符与 pdb_ 前缀扩展格式；ATP 等三字符配体代码不是 PDB ID。区分本文结构、引用结构、用途待核对；记录页码和上下文。仅来源明确时关联 Compound。空白只代表未记录，不能自动判定文章未报告。

## 已查看、需核对与提交

只在 Compound 和 Lineage 两层记录已查看。主动选择 Compound 或 Lineage（含打开其 Edge 详情）后记录；后台加载和浏览整张图不批量确认所有组。Compound 包含基本信息、结构、来源图、活性及关联证据；Lineage 包含成员、成员化合物内容、Edge 及关联证据。相关内容变化使所属组已读失效，无关组不受影响；可以标记未读。只显示这两类计数，结构、Activity、Edge、Evidence 不再分别打勾。文章信息保留人工区段确认；无归属 Evidence 在证据库查看，由最终整篇确认覆盖。旧细粒度回执不自动升级为整组阅读，需要重新打开当前组。颜色仅辅助，文字为准。已查看不是科学批准，不清空“需核对”，不自动确认 Structure/Edge。无内容区段仍需明确未报告，最后须人工勾选整篇确认并提交，Admin 再审批。

## 冲突与保存

科学记录保存使用 Workspace 版本；发生冲突时重新读取并核对，不覆盖别人的修改。布局有独立版本，已读不增加科学版本。需要核对的记录可保持提示与草稿；不要为通过提交检查而随意确认。

## 基团缩写速查

| Symbol | 含义 | 核对要点 |
|---|---|---|
| Me | 甲基 | –CH₃；OMe 含额外的氧连接。 |
| Et | 乙基 | –CH₂CH₃ |
| n-Pr / i-Pr | 正丙基 / 异丙基 | –CH₂CH₂CH₃ / –CH(CH₃)₂；连接位置不同。 |
| n-Bu / i-Bu / s-Bu / t-Bu | 丁基异构体 | 分别为正丁基、异丁基、仲丁基、叔丁基；不能互换。 |
| Ph | 苯基 | –C₆H₅；直接通过芳环连接。 |
| Bn | 苄基 | –CH₂C₆H₅；比 Ph 多一个亚甲基。 |
| Be | 铍（元素符号） | 不是标准苄基或苯基缩写；不得自动纠正为 Bn/Ph，先核对原文定义或印刷。 |
| OMe / OEt / OBn | 甲氧基 / 乙氧基 / 苄氧基 | 通过 O 连接；不同于 Me/Et/Bn。 |
| Ac | 乙酰基 | –C(=O)CH₃；OAc 为乙酰氧基，保留连接原子。 |
| Boc | 叔丁氧羰基 | 常见氨基保护基；记录结构中实际连接位置。 |
| Cbz / Z | 苄氧羰基 | 保护基，不等于 Bn。 |
| Fmoc | 芴甲氧羰基 | 保护基；按图核对连接。 |
| Ts / Ms / Tf | 对甲苯磺酰基 / 甲磺酰基 / 三氟甲磺酰基 | 与 OTs/OMs/OTf 的连接原子不同；注意盐和共价基团的区别。 |
| Ar / HetAr | 芳基 / 杂芳基（泛指） | 不是唯一结构；结合具体定义和取代位置。 |
| R / R¹ / R² | 变量基团 | 只有在该化合物的取代表中明确后才能展开。 |
| o- / m- / p- | 邻位 / 间位 / 对位 | 二取代苯环通常对应 1,2 / 1,3 / 1,4；仍核对编号体系。 |

PDB format reference: https://www.rcsb.org/docs/general-help/identifiers-in-pdb
