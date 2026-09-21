# DeepSeek 预填质量审查与指南改良 — 2026-09-20

结论：技术格式稳定不等于提取质量稳定。真实 005 仍漏主活性系列化合物，010 标签覆盖较好但有区域异构错误，013 有系列级结构连接和表格行列映射错误。当前不能报告一个可靠的“整体准确率”，也不能以此宣称已实现稳定降本增效。

## 范围与方法

Codex 沿用用户要求，仅监督并读取候选、manifest、审查记录，不阅读原始论文内容。文件 hash/大小为程序计算；原文/图片核对由三个新 DeepSeek harness 完成，另对 005/013 的审查缺陷发起有限修订。原始三任务均退出 0，详见各目录 process.json。AI 审查不等于人工金标准；同一模型的新进程仍有共同偏差。

技术审查覆盖旧 007/009/020、round2 005/010/013、真实 005 label-repair，共七份候选（不是七篇不同论文）。科学复核聚焦真实 005、round2 010/013。005 是旧科学候选的标签修订，不能当作 DeepSeek 新提取的首轮结果。010/013 本轮候选未应用到 Preview。本次没有修改 Preview 科学数据。

每篇先建立源标签清单再比较候选，按 `CompoundInventory` 与现有 `check_compound_coverage` 重算。此次候选与源同目录，先看源是提示词约束，不是强制盲审。v2 指南建议分两个进程且调查目录不放候选。活动检查固定 20 个均匀索引并增加风险项；样本不是随机全篇代表，不能外推总体准确率。

## 外部任务身份错误

round2 的 005 实际 PDF/candidate 标题为 ssDAF-12、DOI `10.1021/acs.jmedchem.3c02421`，source hash `f84e8981…` 属于 manifest 001。目标 005 Dual Inhibitors 应是 DOI `10.1021/acs.jmedchem.4c00045`、source hash `e7be3330…`。

最近一轮三任务中：文件/input/candidate 自洽 3/3、离线技术 error=0 的 3/3，外部目标身份匹配只有 **2/3（66.7%）**。这不是分子准确率。错误 005 不算目标文章交付，也不能把它的 16 compounds 和真实 005 的 41 compounds 相减评价漏填。

上轮 label 修复输入还复制了错误 byte_size 10,048,851，实际是 7,549,810；Preview 完整性检查已拦截，后续独立候选修正来源元数据。此处保留历史记录，不重写旧文件。round2 supervision-report.md 已加勘误。

## 化合物覆盖：按明确范围报告

| 核验候选 | 受测系列/主清单 | 纳入正文参考药后 | 主要缺口 |
| --- | --- | --- | --- |
| 真实 005 label-repair | **41/58 = 70.69%**（Table 1/2 受测系列） | **41/74 = 55.41%** | 17 个受测化合物 + 16 个正文参考/控制身份 |
| 010 round2 | **26/26 = 100%**（本次 main narrative 清单） | 同左 | 本次清单未发现缺标签；不证明结构正确 |
| 013 round2 | **66/66** 受测系列，另有 ifenprodil 控制 | **67/75 = 89.33%** | 8 个正文 Figure 1 背景/参考身份 |

以上分母来自 DeepSeek 独立进程源文清单，经 Codex 程序校验/重算；仍不是人工穷尽金标准。005 broader scope 包含 RAS（表题提到但无数据行）、文献参考 A–J 等，不能把它们都叫漏掉的受测实验。013 的编号 3 与 ifenprodil 经审查合并为同一身份，修正了初稿重复计数的 76 分母，得到 75。

005 缺少的 **17 个受测标签**：74、75、76、77、78、79、80、81、83、84、85、86、87、89、90、91、92。源定位：PDF p.8 Table 2。缺失控制/参考：AAZ、MTZ、SEL、CLO、RAS、A、B、C、D、E、F、G、H、I、J、SLC-0111；身份冲突和无数据行情况见 005 audit-v2.json。

013 broader scope 缺失：1、2、4、5、6、7、8、9；来自正文 Figure 1/Introduction，Methods-only 中间体不在这个分母。是否属于用户希望保留的正文目录范围应保持显式，不可因无活性而悄悄剔除。

## Activity 抽查：不要混算准确率和漏项

| 候选 | 活动总数 | 固定 20 行抽查 | 含风险追加样本 | 限制 |
| --- | ---: | --- | --- | --- |
| 005 | 307 | 20/20 核心值/单位/符号匹配 | 另列 9 项 SI/控制覆盖缺口，不进入已有行准确率 | SD/条件整行未完整核验，整行准确率未知 |
| 010 | 314 | 20/20 审查判为匹配 | 31/31 审查样本判为正确 | AI 源文抽查；部分理由偏重值/单位/符号，不宣称全量所有条件正确 |
| 013 | 160 | 19 正确、1 错误，即样本 95%（复审后） | 30 正确、5 错误 / 35，即样本 85.71% | 追加样本有意偏向高风险，85.71% 不是总体准确率 |

005 审查报告另给出主表数值覆盖 307/446（约 68.83%），限定 Tables 1/2 可计数数值单元格；不覆盖所有 SI 阈值、图形数据或 ADMET，全球分母未知。此数字是源文审查者的计数，不用 307 条候选自身定义分母。013 主结合表 Tables 1–4 审查称 71/71 数值覆盖，但 Tables 5–13 不全，因此“主表完整”不能推广成论文全部 Activity 完整。

013 具体源文审查缺陷：

- **审查误报已撤回**：初稿对 Tables 9–11 MCAO 错行、Table 6 数值错误和 Table 5 三个值漏填的判断，第二轮源文复核均撤回。候选在这些检查项上原本正确，不能盲从审查者修改。Table 5 实际 12/12；35 行的结论由初稿 22/13 更正为 30/5。
- Table 12 把 APD30/APD90、APA/Vmax 列混淆，delta% 与 ms/mV 单位错配。
- Table 13 的 L929 细胞名附近出现候选 `1.929 μM`，审查读到的源值是 `>300 μM`；需按原图复验整个表，不只修一项。

以上是 DeepSeek 源文审查发现，行索引/expected/observed 保存在 activity-checks 文件。Codex 检查样本索引不重复、覆盖固定抽样索引、标签确实对应被检查的候选行；没有把自己未读的原文称为独立确认。

## 结构与关系

| 候选 | 高风险结构样本（正确/错误/未决） | 扩大检查发现 |
| --- | --- | --- |
| 005 | 6/0/0，共 6 个 | 不是全 41 个的准确率；共享 bbox 经复审包含骨架与定义，不能仅因共享判错 |
| 010 | 4/2/1，共 7 个 | 3a、10a、11a、14a、15a 的候选 indole F 在 C5，审查源文判应为 C6 |
| 013 | 2/5/2，共 9 个 | 候选 17–21、23–72 共 55 个缺少审查者指定的 phthalide 骨架连接，闭环编号冲突扩散到系列 |

Codex 使用 RDKit 独立核验候选图：确认上述 55 个缺失 phthalide 子图，确认 010 五个指定标签的氟位置为 C5。源文应有结构仍来自 AI 审查，不能把候选图检查当原文核验。013 的 55/67 是受影响候选数量，不是“另外 12 个全部正确”的证明。立体化学、盐型及原文命名冲突仍需复核。

SAR 与 synthesis 的全图覆盖分母均未穷尽，报告 null。005 旧候选 5 条 Lineage 未显式填 lineage_type。005 审查初稿错误地声称没有 nested edges，修订后正确读取 `payload.lineages[].edges[]`；但 ref/成员/证据链接完整只证明结构一致性，不足以把 35/35 记为科学关系准确率。审查中按 edge_ref 跳号猜测缺失数量的内容不采纳。010/013 的局部 edge 疑点保留在明细，不把无文本 Evidence 本身作为错误。

## 对审查结果的纠错

监督者发现并反馈三类审查缺陷：013 的 3/ifenprodil alias 重复分母；005 误说候选无 nested edges、误把 shared bbox 当不完整；005 把 missing source 项计为现有行错误。第二轮还撤回 013 初稿 MCAO/Table 6/Table 5 误报。报告使用修订明细，不能引用早期 22/35 作为最终准确率。013 v1 有部分报告被 harness 在生成 v2 时更正；不是所有 v1 文件字节均保持原样，source-inventory 初稿和初始 activity-checks、日志仍保留。候选科学文件未变。

005 v2 edge 报告仍按 edge_ref 缺号提出数量猜测，以及“35 个有效引用即 35 个科学正确”的概括，不进入监督结论。原文未给出的全局准确率仍为 null。

## 根因与文档改良

1. **外部身份检查缺失**：input 与 candidate 互相校验掩盖错源。v2 增加 manifest/catalogue → PDF/input → candidate → Preview 全链核对；实际 DOI/title 由有原文权限的 harness 读取。
2. **指南没有真正进入启动包**：round2 三篇实际 guide 副本与仓库当前版不同；prompt 缺质量记录和可计算 inventory 交付要求。v2 给指南包逐文件 hash、运行版本与启动前存在性核验，历史包保持原样。
3. **没有执行阶段验收**：已有“不要重复 SMILES ring digit”的提醒，013 仍复发。v2 要求每核心代表结构验收产物后才展开，并保存 numbered atom mapping。
4. **候选限制提取范围**：真实 005 label 修复只继承已有 41 个。v2 要每张源表独立清点，先冻结 inventory；结构未决不能从分母消失。
5. **表格扁平化错位**：先保存含 model/vehicle/剂量/时间的完整行列映射，核对原始 token 和页/表/行/列后转换。
6. **审查报告也会错**：v2 明确 alias 去重、C/E/U/N/P 重算、已有行准确率与源遗漏分离，shared crop 只按内容是否完整判断。
7. **应用流程误解**：文档明确 apply 只支持空白 untouched workspace；局部标签用 reviewer PATCH 与版本保护，不能把版本参数当 replacement。

已更新 extraction-guide.md、deepseek-supervised-runbook.md、deepseek-quality-checklist.md、task/revision prompt 和 quality sidecar；新增 quality-audit-protocol.md、deepseek-audit.md。运行版本 `deepseek-supervised-v2`，数据候选 schema 仍 v1。快照在 guides-before；可分发包在 guide-bundle-v2，hash 清单见 guide-bundle-verification.json。

## 验证与后续边界

- 重跑七份候选离线技术检查，外部 manifest 对照结果保存在 technical-audit.json。
- 三份清单经格式适配通过现有 CompoundInventory 验证与覆盖比较（013 harness 再次加入三个契约外汇总字段，监督者将它们移至 inventory-extra-sidecar.json，entries 原样保留于 inventory-normalized.json）；样本索引/标签与候选一致，明细重算见 recomputed-metrics.json。
- 候选文件 hash 未变化；本次仅审查与指导文档改良，不自动替换 Preview 或清理科学数据。
- 指南 JSON 可解析、本地链接检查通过，sidecar 默认 not_reviewed、总体准确率 null；新包逐文件 hash 已记录。
- v2 是针对已发现缺陷的改良，尚未进行同一标准的新提取 A/B 实验，不能量化声称降低失误率或节约了多少费用。

下一批修复优先级：013 共享结构与 Tables 12–13 → 010 五个区域异构体与未决结构 → 005 17 个受测化合物及关联测量/关系，再处理正文参考物。修复必须使用正确来源、新 candidate ID 和完整 affected-series 检查；目前本报告不构成候选科学放行。

完整可复核产物：[审查目录报告](/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/deepseek-quality-audit-20260920/report.md)。
