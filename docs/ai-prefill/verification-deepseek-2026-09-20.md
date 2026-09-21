# DeepSeek harness：三篇新论文预填试验

用户要求：指导本机 DeepSeek harness 完成新论文预填，并观察实际效果。

## 实验方法

- Harness：本机 `dsh 0.1.5-rc.2`，配置/运行时模型标识 `deepseek-flash`。
- 论文：已有 first20 原文基线中尚未预填的 007（C5aR1）、009（Juglone/PDI）、020（VISTA）。
- 输入：原始 PDF、从同一 PDF 提取的文字、CandidateEnvelope schema、提取指南、任务 prompt。未提供旧 CSV 的科学答案，也未提供数据库或账号凭据。
- DeepSeek 自己调用文件、Python、图片工具，生成提取/结构脚本、候选、原图坐标、遗漏说明。宿主独立读取原文、重绘结构、核对数值，给出具体反馈后由 DeepSeek 修改候选。
- 第一轮、反馈、修订版、验证结果和应用凭据均保留。错误的第一轮候选未写入 Preview。
- 这是有指导和人工代理反馈的小样本工程试验，不是盲测，也不能据此估计通用正确率。

外部实验目录：
`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/deepseek-prefill-20260920`

## 首轮结果与真实缺陷

| 论文 | Compound | Activity（含 PK/ADME） | 原图定位 | 有原图关联的 Compound | 检出的错误结构图 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 007 | 54 | 207 | 15 | 13 | 53 |
| 009 | 28 | 254 | 41 | 26 | 14 |
| 020 | 23 | 41 | 25 | 23 | 0（本次检查未发现） |

三篇首轮都能通过 schema/RDKit 技术验证，只返回无支持 Evidence Edge 的非阻断 needs_review。但独立重绘发现：007 的 53 个结构和 009 的 14 个结构由字符串拼接时重复使用尚未闭合的 SMILES 环编号，生成原文没有的三元内酰胺/大环。分子式和 HRMS 质量相符不能证明原子连接正确；canonicalization 也不会修复已经错误的分子图。

原图方面，007 将一组共享骨架只关联到一个代表化合物；009/020 的部分化合物只有取代基行，看不到关联在别的化合物上的骨架。007 第二版虽然补上所有关联，仍存在 5b 连接基和标签裁剪截断、部分 L 连接基定义没有包含的问题，需要第三轮截图反馈。

宿主独立从原文建立了两组、共 **206 项**数值/比较符号/ND 对照检查：全部匹配。该数量包含重复参考行和 ND 检查，不应误称 206 个独立实验；检查也不覆盖所有 SD、实验条件及所有原文单元格。

## 反馈与修订

- 007 / 009：DeepSeek 改用独立片段的原子/键拼接，消除 SMILES 环编号冲突。宿主对全部最终结构重新绘图，确认 53 / 14 个结构图变化，未再出现原文不支持的大环；按原文检查核心、取代位置和环大小。
- 007：将 CYP3A4、2D6、2C9 的共同阈值分别记录；将 5 个单独“oral dose”条目移到 PK 实验条件，保留真实 PK/ADME endpoint，Activity 为 206。
- 009：保持 254 Activity。每个 JUG 化合物关联自己的骨架和取代基行；aspirin/bortezomib 没有原文结构图，描述明确说明使用已知参考药身份，未伪造截图。
- 020：保持 23 Compound、41 Activity、21 Edge；每个 A/B 化合物关联自己的共享骨架和取代基行。修正 A9 羟基标签及 A12/B10 底部裁剪边界。
- Edge 可没有文字证据或任何支持 Evidence；推断理由保留，应用后仍为 DRAFT。方向是待审核的 SAR 组织方式，不能解释为已证实的实验时间顺序或因果链。

## 最终修订候选

| 论文 | 版本 | Compound | Activity | 原图定位 | 有原图的 Compound | Edge（无支持 Evidence） |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 007 | v3 | 54 | 206 | 56 | 54 | 44（44） |
| 009 | v2 | 28 | 254 | 65 | 26 | 24（24） |
| 020 | v2 | 23 | 41 | 45 | 23 | 21（17） |
| 合计 | | 105 | 501 | 166 | 103 | 89（85） |

007 v3 仅修改截图定位及说明；宿主验证 compounds/activities/lineages/evidence/links 与已检查的 v2 完全相同。共享表格区域可以重复关联到不同化合物，因此 166 是定位记录数，不是 166 张不同独立结构图。三篇需按具体原文区域判断完整结构身份；009 的两种无图参考药已有说明。

## 科学边界

- Activity 含活性、选择性、理化性质、ADME 和药代参数，并非全部是 IC50/KD。
- 同一测量在不同表重复报告时可能保留不同表格上下文，例如 009 的 Table1/Table4 rPDI；不能把所有条目视为独立重复实验。
- 009 糖基异头构型及源文命名/NMR/图示差异、14/29 的 HRMS 印刷疑点需要人工复核。19 保留异头混合物的未指定中心。
- 020 参考 compound2 的互变异构/双键几何及 B10 构型仍供人工复核；未将无数值的柱状图或缺失 SI 猜成定量值。
- 无图的两种参考药、缺失 Supporting Information 和图形数据等均保留遗漏说明。
- 修订后候选用于人工审核预览，未被标记为人工科学审核通过。

## 复现与验收证据

- `experiment.json`、各论文 `input.json` / `prompt-v1.txt`：源文件身份、选文和指导条件。
- `candidate-v1.json` / `review-notes-v1.md`、`work-v1/`：不可覆盖的原始结果。
- `host-feedback-v1.json`、007 `host-feedback-v2.json`：宿主具体反馈。
- 当前 `candidate.json` / `validation.json` / `review-notes.md`：修订输出及覆盖范围。
- `independent-review/first-run-scorecard.json` / `current-graph-check.json`：宿主结构图差异检查。
- `independent-review/reference-check-current.json` / `additional-check-current.json`：原文数值对照。
- `independent-review/*-delivery-review.json`：绑定精确候选 hash 的预览接收检查。
- `applications.json` / `receipt-verification.json`：实际 Preview 应用及数据库凭据核验。
- `browser/verification.json` 与截图：实际 LAN 页面、逐字段 Activity、所有原图 PNG、分页、筛选、旧四篇版本保持检查。
- `artifacts/experiments/deepseek-pilot-20260920/`：独立保留的候选/反馈/快照链。

## 最终交付验收

三篇修订候选已实际应用到原有 LAN Preview（`http://10.21.53.251:18080/review/tasks`），应用回执均为 `committed`，新工作区版本均为 2。最终健康检查为 `ready`，原有两个账号登录检查通过。任务列表共 7 篇，原有四篇的版本保持不变；004 的 `changed_since_apply` 来自先前已存在的 N-Boc/N-Cbz 注释修改，不是本次实验修改。

实际 Chromium 页面验收通过：501 条 Activity 的页面字段与最终候选一致，166 个原图 PNG 均成功解码；分页、化合物筛选和 Lineage 页面已检查，无 JavaScript 错误或科学数据写请求。89 条新增 Edge 均为草稿，其中 85 条没有关联支持 Evidence。页面一致性检查与上述 206 项原文对照检查各自独立，均不等同于全部科学内容已获人工批准。

当前运行核验记录保存在 Preview 目录的 `enrichment/current-preview-verification.json`，浏览器验收保存在实验目录的 `browser/verification.json`。账号、端口和原有四篇审核内容沿用原状态。

## 操作错误说明

任务途中宿主误将终端 session ID 传给 cell 等待工具，导致 `cell not found`；这不是 DeepSeek 提取失败。三篇首轮后台均已 exit0 并写出候选。恢复后直接读取持久结果，没有重跑第一轮。`run-results*.json` 的逐任务 elapsed 来自按顺序 wait，后面的数值可能是批次等待上界，不能用来做精确的逐论文耗时比较。
