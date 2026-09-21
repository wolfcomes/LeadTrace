# DeepSeek 预填质量检查清单

与 [运行指南](deepseek-supervised-runbook.md) 配套，版本 `deepseek-supervised-v2`。每项填写 `pass / fail / uncertain / not_applicable`、实际检查范围、证据文件和检查者。尚未检查写 `not_checked`，不得默认 pass。本文件是操作检查清单，不是已实现的新 validator。

## v2 交付门禁与指标

- 任务源身份同时对照外部 manifest/catalogue；input 与 candidate 互相一致不能证明文章选对。
- source DOI/title 必填于任务输入的外部预期身份；harness 核对实际 PDF 首页。错误包隔离为 `blocked_source_identity`，不记为目标文章已交付。
- `compound_label` 为原文打印标签；保留字母/异构体/prime/无编号药名，解释性名称放 display_name。
- 独立清单先于候选读取落盘，逐项有页码/表格和 scope；required 标签缺失不可用 omission 或不确定结构从分母中移除。
- 指南、prompt、schema 实际复制到 job，逐文件 hash 入账；存在 template 不等于实际执行过阶段验收。
- 报告 C/E/U（正确/错误/未决）和 N（实际检查数）、P（候选总数），C+E+U=N；不能将未决移出分母。
- 主指标 `confirmed_fraction=C/N`；`C/(C+E)` 只能另列为已解决样本准确率；全量准确率未核验时为 null。
- Activity 行按 compound/target/endpoint/value/unit/operator/conditions 整行核对；单元格正确不能记整行正确。
- 结构、原图身份、SAR edge、synthesis edge 分开统计；可加载截图与视觉核验不混算。
- 独立审查是新 AI 进程，不是人工金标准；样本的选择方法和候选 hash 固定并公开。
- 详见 [审查协议](quality-audit-protocol.md)。以下旧 `DS_*` 及新增身份/覆盖标签均为操作记录，不是已部署的 API 错误码。

## 源与覆盖

- 实际 PDF 的 SHA-256、字节数、页数与 input 一致；页码为 PDF 的 1-based 页序，不是印刷页码。
- 已调查正文全部结构/SAR/药理/ADME/PK 表、图、正文和脚注；缺失 SI 明确列出。
- 每张表列出预期化合物标签、实际提取标签、遗漏及原因；无可提取文本的表已渲染检查。
- 未用旧 CSV 的空栏推断论文没有 Activity；未用候选本身生成覆盖率分母。

## 结构身份：预览前必须检查

- 每个不同核心、连接基变体和立体化学风险都经过早期代表结构检查。
- 全部最终结构均可解析，且最终带标签重绘逐一与原图对照。没有把“执行了绘图脚本”等同于“看过图”。
- 检查共享核心、连接原子、环大小、取代位置、保护基、形式电荷、立体化学；N-Boc/N-Cbz 等名称与图示冲突单独列出。
- 未发生 SMILES 未闭合环编号冲突；canonicalize 和 HRMS/分子式一致仅为辅助检查。
- 异常小环或大环触发源图复核，不一刀切删除真实环；稠环/桥环按实际图判断。
- 未确定的异头中心、混合物或互变异构按源文表达；没有偷偷指定原文未给出的构型。
- 无法可靠确定的结构明确遗漏，连带列出未提取 Activity/Edge，未用占位结构凑数。

## 原图：能加载与内容完整分别验收

- bbox 是 top-left origin 的归一化正面积矩形；使用正确页面尺寸，旋转页通过实际裁剪核验。
- 每个 compound 的自身 locator 集合都包含其完整身份信息：共享骨架、目标行、取代基/连接基定义、标签。
- 共享核心没有只关联到一个代表化合物；按不同 compound 统计覆盖率。
- 检查所有最终 crop；尤其首末行、列边界、底部脚注、5b 类连接基、羟基/电荷标签和相邻控制行。
- 小图看不清时提供完整区域和大图入口；可增加局部原图，不把 RDKit 重绘当作 source crop。
- 共享区域注明 shared；原文没有结构图的控制药明确说明，不伪造独立结构图。

## Activity 与 Evidence

- 对照真实表头和脚注确认 compound 行、target、assay、endpoint、单位和比较符号；首行、中间行、末行及所有异常值纳入检查。
- 关键主活性、lead/reference、表头映射、单位、阈值、ND 和所有反馈影响范围优先全查。其余若抽查，记录样本清单和未查数量，不能声称全量科学准确。
- 缺失、ND、范围和定性结果不写 0。真实负抑制率不因负数而被删除；pIC50 不静默改写为 IC50。
- SD/SEM、n、原始单元格、物种、细胞系、给药途径/剂量和时点按可用字段或 context 保留。
- 分清共同报告的多靶点阈值与未报告数据：例如明确适用于 CYP3A4/2D6/2C9 的阈值逐靶点记录；不扩展原文没有覆盖的靶点。
- 给药剂量是 PK 条件，非独立药效 endpoint；ADME/PK 参数有实际测量时保留。
- 重复表格数据保留上下文且不计为独立重复实验；控制药和单位不同的列不串行。
- 定量结果可追溯到真实 Evidence；table 的 caption 是说明，quoted_text 只有真实原文引用才填写。
- 数值对照由检查者从 PDF 独立读取，未用 candidate 自动生成期待值。分歧时放大源图，不假定检查者转录一定正确。

## Edge

- 每次补充 compound 后重新清点 Lineage members 和 Edge；不得把“化合物已齐”当作“关系已齐”。
- 独立列出各 SAR 轴、已命名反应箭头及期望端点，逐项记录已提取、缺失或暂缓原因；列出未加入任何 Lineage 的 compound 供复核，不强制每个 compound 都有 Edge。
- 区分母体/SAR 基线比较与直接合成前体；比较箭头不代表合成步骤、研发先后或活性提升，不跳过已命名中间体。
- 无文字证据不能单独成为排除理由；真正未确定的 parent 和结构身份冲突仍需明确暂缓，不批量把旧 unresolved 升格为 AI inference。
- 原文段落、Scheme 和结构编号不一致时保存冲突与采用的依据。示例：PfPKG 的 nitrile 水解应核对 Scheme 5 的 23→26，不能机械采用正文误写的 22。

- 两端属于候选内可识别化合物，没有自环或被明确否定的关系。
- 区分合成步骤、结构变化和 SAR 推断；不从编号或活性排序直接推断时间/因果。
- 无文字或支持 Evidence 仍可有 Edge；`modification_summary` 明确写 AI inference 和具体理由，不造引用。
- 缺少 Evidence 的 Edge 属于非阻断审查项，不能为了清空 warnings 而删除合理推断或制造证据。
- Preview 中所有 AI Edge 为草稿，供人工确认或标为未解决。

## 版本、交付与停止条件

- 技术验证报告对应精确候选；`invalid` 不应用。`needs_review` 逐项解释，未被误报为科学通过。
- 原候选保留，新候选有新 ID、正确 parent 和实际反馈 IDs；本地反馈与正式 Evaluation 类型区分。
- 比较修订前后结构、Activity、locator 和 Edge，检查修裁剪时是否意外改变科学数据。
- 科学放行绑定候选文件 hash；后续内容改动使旧放行失效。
- 监督者核验 source、实例、工作区版本、应用回执；页面全部 Activity 与候选对齐，PNG 可加载，来源内容可核对。
- 没有改写原有人工编辑；没有把“进入 Preview”标为“人工科学批准”。
- 超出修订或费用预算，或同类缺陷重复无改善时，保存产物并升级处理；不无限重试或降低标准凑交付。

## 本次失败模式速查

以下 `DS_*` 是人工检查标签，尚未注册为程序 validator 返回码。

| 检查标签 | 本次实例 | 修复与复验 |
| --- | --- | --- |
| `DS_GRAPH_CONNECTIVITY` | 007 的 53 个、009 的 14 个图连接错误，但 RDKit/分子式可通过 | 重建片段连接，检查整个系列的核心/环/取代位置及重绘 |
| `DS_SOURCE_PER_COMPOUND` | 007 首轮仅 13/54 个化合物有原图关联 | 每个 compound 自身关联核心与目标行，按不同 compound 计数 |
| `DS_CROP_IDENTITY` | 007 v2 的连接基截断；020 羟基/底行边界问题 | 放大真实 crop，包含所有定义，复查每张最终图 |
| `DS_ACTIVITY_CONTEXT` | 给药剂量单列为 Activity；共同 CYP 阈值未展开 | 分清 endpoint 与条件，核对原文后逐靶点记录 |
| `DS_REVIEW_REFERENCE` | 检查者将 009 的 1.82 抄成 1.84 | 回到放大的源表纠正检查参照，不盲改正确候选 |
| `DS_PROCESS_WAIT` | session ID 与 cell ID 混用 | 查询真实进程与文件，用匹配的等待工具恢复 |

## Typed SAR and synthesis Lineages; catalogue scope

- [ ] Each new Lineage is explicitly `sar` or `synthesis`; legacy unknowns stay
  `unspecified` until reviewed. Grouped UI labels must not substitute for this field.
- [ ] SAR baseline arrows do not imply chemical precursor, chronology or improved
  potency. Synthesis arrows do not imply an Activity result.
- [ ] Main narrative/SAR Compound scope is explicit. Experimental-only intermediates
  and free-base/salt forms are retained in route details/Evidence without inflating
  the main catalogue. Main-text intermediates can have honest empty Activity.
- [ ] Every synthesis edge is checked against experimental procedures and Schemes;
  precursor substitutions, omitted protecting-group steps and salt forms are clear.
- [ ] A route summary is explicitly distinguished from a single reaction; all known
  omitted steps are described. Unsupported direct edges are removed/replaced.
- [ ] Cleanup has a before snapshot and ID-level keep/correct/delete journal. Shared
  Compound/Activity/Evidence are not deleted merely because an old Lineage is stale.
- [ ] Separate SAR coverage and synthesis-route coverage; do not claim experimental
  completeness from complete SAR table coverage or successful schema validation.

## 本轮新增的具体复验项

- 013 共享 lactone/piperazine 结构生成必须保存代表结构批准记录，之后按系列全查环闭合与连接点；没有记录不批量扩展。
- 010 吲哚区域异构：把 R 标签映射到编号原子，逐项检查 5-F/6-F，不能仅按 SMILES 外观判断。
- model/vehicle 对照与剂量/时间必须随完整行读取。013 初审关于 Tables 9–11 错行的结论经回源已撤回；不得把审查误报当修复目标。
- Table 12 逐列确认 APD30、APD90、APA、Vmax 和 delta%/absolute 单位；Table 13 的 L929 是细胞名，必须防止 OCR 数字误识别。
- 005 每个主活性表独立清点，Table 2 不能从旧候选限定范围；选择性比值、阈值与控制药另列覆盖。
- inventory 中主文编号与控制药名称可能指同一身份，alias 去重；盐型真正不同则保留不同身份且不共享含糊 alias。
- 审查者必须读取 `payload.lineages[].edges[]` 的实际端点与类型，不能把 `edge_evidence_links` 数量当 Edge 总数或从 edge_ref 猜端点。
- 013 的 MCAO/Table 6/Table 5 初审误报已回源撤回，先复核 expected 参照再改候选。审查者的错读/重复分母也要反馈修订，原始结果与修订日志保留。缺失 source 项不混入已有 Activity 行准确率。

## 交付前自检

遵循 [DeepSeek 自检指南](deepseek-self-check-guide.md)。提交最终hash绑定的self-review.json、程序生成的self-check.json及修正/未决记录；程序检查与原文核对分别报告。
