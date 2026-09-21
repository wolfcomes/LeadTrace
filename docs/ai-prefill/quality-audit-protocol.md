# 预填覆盖与准确性审查协议

运行版本：`deepseek-supervised-v2`；CandidateEnvelope 仍为 v1。本文件是操作协议，不新增 API validator，也不自动修正历史候选。现行验收补充见 [常见质量问题](quality-pitfalls.md)。

## 1. 分开评估四个层面

| 层面 | 分子/分母或判定 | 不能替代的检查 |
| --- | --- | --- |
| 任务身份 | 外部 manifest/catalogue 匹配的任务 / 派发任务 | 同一个错误 input 与 candidate 互相一致不算通过 |
| 化合物覆盖 | 已匹配的 required 源标签 / 独立清单 required 标签 | 不证明结构正确，不以 candidate 自己作分母 |
| 测量覆盖 | 按来源匹配的测量 tuple / 预先清点的源测量 tuple | 不把 Activity 总数当原文测量数，不把不同表重复报告当独立实验 |
| 科学准确性 | 独立源文核对的正确项 / 实际检查项，未决单列 | schema、RDKit、图片加载和作者自检不等于准确 |

必须报告候选文件 hash、版本、源文件 hash、原文访问者、审查范围、样本清单与选择方法。旧轮与修订轮各自统计；不同源、不同口径的分母不能相加。错误来源任务对原目标没有有效交付，但不推断其实际提取那篇论文的科学准确性。

## 2. 运行前的身份门禁

监督者从可信 manifest/catalogue 按 paper_key 选源；禁止从 filename 顺序或另一个任务复制大小/页数。记录实际 `SHA-256/byte_size/page_count`，输入同时给出预期标题和 DOI。来源身份要贯通：

`外部任务清单 → 任务包 PDF → input → candidate.source + bibliography → Preview paper/source`

逐环不一致则 `blocked_source_identity`（操作状态）。特别是 `source.doi` 可选不能成为绕过文章身份核对的理由。harness 读取真实 PDF 首页核对标题/DOI；监督者只读元数据时，记录该观察者身份。任何模型自报的标题/DOI 不是外部清单本身。文件字节 hash、canonical candidate hash、payload hash 分别保存。

例：round2 的 005 input/candidate/PDF 彼此一致，但源 hash 实际属于 manifest 001（ssDAF-12），而目标 005 是 Dual Inhibitors。随后 label 修订输入还复制了错误的 byte_size。这两类错误不能依靠 schema 校验发现。

## 3. 先清单，后比较

独立审查进程开始时不提供旧 review-notes、预期科学答案或已知缺失标签。先读取 PDF，落盘清单，保存 hash，再开放候选比较。提示词要求不是强制访问隔离；需要盲审保证时分成两个进程阶段，调查阶段目录内不放 candidate。只有日志显示先保存清单再读取候选，才记录顺序要求已满足。

清单遵循已有 `CompoundInventory` v1：

```json
{
  "inventory_version": 1,
  "source": {
    "paper_key": "ACTUAL_KEY", "source_sha256": "ACTUAL_SHA256",
    "byte_size": 1, "page_count": 1, "doi": "ACTUAL_DOI"
  },
  "scope": "正文/SAR/控制药；Methods-only 中间体另存路线",
  "reviewed_by": "ACTUAL_REVIEWER_AND_AI_OR_HUMAN",
  "entries": [
    {
      "label": "1a", "aliases": [], "required": true,
      "role": "assayed", "source_locator": "PDF page/table/row",
      "exclusion_reason": null
    }
  ]
}
```

以上是说明格式的占位示例，不能直接使用。required=false 必须给出具体 exclusion_reason；alias 需真实来源支持。枚举原文实际标签而非补齐数字范围。`compound_label` 保持打印身份，解释性名称分开。

主目录只纳入正文/SAR/控制药及正文明确讨论的中间体。Methods-only 中间体、盐型转换保存在路线细节，不能为了把合成图画满而扩大目录。主文确有化合物、但结构无法表示时仍算未完成；当前结构必填的契约限制要公开，不用占位 SMILES。

运行已存在的模块：

```bash
python -m leadtrace.ops.ai_prefill candidate coverage candidate.json --inventory compound-inventory.json
```

缺失 required 标签退出 4；省略说明不使其通过。此命令只比标签，`scientific_identity_verified` 仍为 false。fresh AI inventory 可能漏项，必须保留页码/表/图并抽查未匹配、extra 和范围边界；不把 AI 自建清单称为人工完整金标准。

## 4. 准确性抽查与完整性清点

按不同任务风险预先固定样本，禁止看完结果后只报告正确项。基线抽查至少 20 行 Activity：N>=20 时索引 `floor(i*(N-1)/19), i=0..19`，N<20 时全取；另补不同表格/靶点/单位/比较符/缺失符号、lead 与控制药。索引从 0 开始。补充样本去重，保留选择原因。

Activity 核对 tuple：compound、target、assay/endpoint、value、unit、operator、conditions（含 SD/SEM、时间/物种等适用上下文）、来源。整行任何字段不一致不能记整行 correct。只有核心数值对上且条件未查时记 uncertain 或另报 field-level 指标，不能偷换整行分母。复查者转录也会出错，分歧回到源表放大核对。

结构抽查覆盖每种核心和高风险连接点/环大小/区域/立体化学/盐型，至少 6 个（不足时全取）；为样本保存原图与 RDKit 对照及实际 image tool 观察记录。没有看图则 uncertain。检出共性错误扩大到整系列。分子式/HRMS 只作辅助。

原图检查单独记录：每个 compound 自身关联是否同时含骨架、取代基定义和识别行/标签。`41/41 有 locator` 不是 `41/41 身份截图完整`。同一组重复共享 crop 的数量不增加结构覆盖分母。

Edge 分 SAR 与 synthesis，记录源清单、匹配/缺失/不确定关系和方向理由。非 exhaustive 清单不报全图覆盖率。AI inference 不需要文本证据；不能因缺 quote 计错误，也不能因有 quote 就免检端点。直接反应与多步摘要分开；Methods-only 节点不强塞主目录。不要把所有结构相似配对作为 required Edge。

## 5. 重算指标，拒绝漂亮但无分母的数字

逐行记录 `correct / incorrect / uncertain`。设 C/E/U 为三类数量，N=C+E+U，P 为候选总数：

- 主报告：`confirmed_fraction=C/N`，同时显示 C/E/U 与 `N/P` 检查范围。
- 可另列 `resolved_accuracy=C/(C+E)`，明确排除了 U；不能用它冒充全部样本的准确率。
- `whole_population_accuracy=null`，除非全量完成且来源基准可靠；小样本/偏向高风险抽样不外推总体百分比。
- 覆盖分母未知写 null，不写 0 或 100%；已有 Activity 的 compound 比例只称“关联比例”。
- 同一 DeepSeek 模型的新进程审查仍有同源偏差，不是双模型确认或人工批准。

## 6. 指南实际生效与交付

每轮任务复制指南、checklist、prompt、schema 和 sidecar template，保存每个文件 hash；检查 prompt 中的全部实际文件存在、无未替换占位符。新质量记录格式为 `deepseek-supervised-sidecar-v2`，不是 CandidateEnvelope 字段。没有清单、检查明细或实际图像观察记录时，门禁留为 not_reviewed/needs_revision，不能从 exit 0 推断完成。

审查结果不可反写成候选“自检通过”。修订生成新候选并重跑精确 hash 的检查。本次仅改文档、审查产物与错误报告勘误；不自动替换 Preview 或补提全部科学数据。已知错误/缺口另发精确反馈，后续交付仍由用户复核。

## 本轮审查反例

013 初审把正确 MCAO 行读错，误报 Tables 9–11 错行、Table 6 数值错误和 Table 5 漏填；回源后撤回，35 行样本从 22/13 更正为 30/5。005 初审则把 missing observations 计入现有行准确率，并误判完整 shared crop。监督者必须核对审查口径和争议参照，不能仅把“换一个 AI 会话”当正确性保证。Edge ref 缺号与科学关系数量没有必然对应；引用存在不能证明关系科学正确。
