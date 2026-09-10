# 项目对话记录与工作上下文

**整理日期：** 2026-09-09  
**最近更新：** 2026-09-10（Batch 05 完成）  
**项目目录：** `/data/home/zhangzhiyong/lead_optimization_collection`  
**项目：** 2024 JMC 分子修改与 lead-optimization lineage 提取

## 说明

本文件整理当前对话中可见的项目需求、设计决策、处理进度和待办事项，作为后续工作的连续上下文。自动注入的浏览器地址、端口和其他 ambient UI 状态不属于用户指令，因此不记录在此文件中。

早期项目背景仍保留在：

`source_pdfs/分子修改提取_2024_JMC/00_conversation_context.txt`

## 一、项目目标演进

### 1. 处理范围

- 原始语料库为 JMC Volume 67 的 672 篇 Paper。
- 早期工作从 16 条测试路径开始，后来扩展为按批次处理进入 lineage 的 Paper。
- 目标是建立可审计的 lead-optimization / SAR 修改链，而不是单纯的合成反应路线。
- 每一步都需要报告 Paper 数、entity 数、edge 数、结构确认数、pair-ready 数和未解决原因。

### 2. 分子结构优先

用户明确要求采用以下顺序：

1. 识别 PDF 中含有完整分子或分子片段的 Figure、Scheme、Table 和对象。
2. 识别编号分子以及 R 基团、链接键和片段替换关系。
3. 对不完整结构图进行结构推理、R-group 展开和完整分子重建。
4. 根据完整结构生成 SMILES，并使用 RDKit 解析、标准化和确认。
5. 最后再记录 parent / derived 关系、修改类型、活性和文字证据。

图片通常只显示片段或带 R 基团的模板，不能把图片中的局部结构直接当作完整分子。编号相邻、结构相似或同属同一 SAR 表，也不能单独证明 immediate parent。

### 3. 可追溯性

每个结构或关系应尽量保存：

- Paper ID、DOI 和 Paper-local compound label。
- PDF 页码、Figure / Scheme / Table 定位。
- 原始证据文本和来源文件定位。
- source、重建、canonical / isomeric SMILES。
- scaffold、R-group assignment、attachment mapping。
- RDKit 状态、结构确认状态和人工审阅状态。
- 无法确认的字段使用 `--` 或 `None`，不伪造结果。

## 二、Dashboard 与审阅界面需求

### 1. Paper 列表与详情

- 672 篇 Paper 显示为 672 个具体条目。
- 每页从 40 篇调整为 20 篇。
- 首页以项目总览为主。
- 移除独立的“结构复核”“OCSR”“证据浏览”等主导航入口。
- 从 Paper 列表直接进入 Paper 详情页。
- Paper 详情页显示该 Paper 的处理进度和 Paper 内的具体内容。

### 2. 阅读模式与修改模式

- **阅读模式：** 浏览 Paper、lineage、结构、证据和 activity。
- **修改模式：** 对未审阅条目进行修改、增删和确认。
- 修改确认后同步到已有总表或保存文件，不能只停留在浏览器临时状态。
- 不同字段使用预定输入格式，例如状态、SMILES、证据定位、关系类型和审阅决策。

### 3. 统一审阅条目

Evidence statements、Candidate modification records、Explicit paths、SMILES / RDKit results 和 activity 合并到统一条目框中。字段缺失时显示 `--` 或 `None`。

### 4. 分子对与 lineage 显示

- 核心审阅单位是修改前后的 compound pair。
- pair 中的两个 compound 作为一个整体展示。
- 最终展示图不截取论文图片，而是根据确认后的完整 SMILES 重新绘制。
- 不再单独展示 “MOLECULE OBJECTS / ATTACHMENT REASONING” 大块。
- Objects 可以保留在 Paper 详情页，但只保留初步过滤后明显包含结构区域的对象。
- 记录完整迭代链：

`root template -> immediate parent -> derived compound`

其中 root template 可以是 1 号分子、已知药物、抑制剂或系列起点；parent 是当前修改的直接上一代；derived 是修改后的分子。

## 三、Lineage 数据规则

### 1. 关系状态

- `text_explicit`：正文明确描述直接修改关系。
- `figure_explicit`：Figure / Scheme / Table 明确支持关系。
- `human_confirmed`：人工审阅确认。
- `unresolved`：只能确认系列归属，不能确认唯一 immediate parent。

`unresolved` 关系可以保留 root 和 derived label，但 parent 使用 `--`，且不得形成 pair-ready edge。

### 2. Pair-ready 条件

只有同时满足以下条件才允许 `pair_eligible=yes`：

1. 关系状态为 explicit 或 human confirmed。
2. parent 和 derived 是不同的 Paper-local entity。
3. 两端都是完整单组分结构。
4. 两端的结构状态都是 `structure_confirmed`。
5. RDKit 可解析，无 dummy atom、radical 或多组分混合物。
6. 有明确且可审计的结构来源和 label 绑定。

### 3. 标签规范化

标签规范化必须保留 Paper-local identity，不能模糊匹配。已支持 compound qualifier、R/S stereochemical label、字母后缀和 Paper 内部编号。

本轮发现并修复了一个重要问题：原来的 `normalize_label()` 会将 `26a′` 和 `26a` 都归一化为 `26a`，造成真实 self-loop。现在：

- `26a` -> `26a`
- `26a′` -> `26aprime`
- `26a'` -> `26aprime`

修复同时应用于 lineage builder 和结构重建脚本，并加入了回归测试。

## 四、批次结果

### Batch 01

| 指标 | 数量 |
|---|---:|
| 请求 Paper | 23 |
| lineage entity Paper | 23 |
| Edges | 308 |
| Explicit edges | 265 |
| Unresolved edges | 43 |
| Entities | 335 |
| `structure_confirmed` | 333 |
| Complete structures | 334 |
| Missing / non-unique structures | 1 |
| Pair-ready edges | 263 |
| 有 pair-ready 的 Paper | 23 / 23 |

Batch 01 是早期基线，explicit 关系比例较高，所有 Paper 都有至少一条 pair-ready edge。

### Batch 02

| 指标 | 数量 |
|---|---:|
| 请求 Paper | 24 |
| lineage entity Paper | 24 |
| Edges | 961 |
| Explicit edges | 816 |
| Unresolved edges | 145 |
| Entities | 990 |
| `structure_confirmed` | 990 |
| Complete structures | 990 |
| Missing / non-unique structures | 0 |
| Pair-ready edges | 816 |
| 有 pair-ready 的 Paper | 24 / 24 |

Batch 02 的结构完整度最好，所有 990 个 entity 都有 confirmed
structure。Prime label 修复后 `26a` 和 `26a′` 作为两个不同的
Paper-local entity 保留，816 条 explicit / figure edge 全部 pair-ready。

### Batch 03

| 指标 | 数量 |
|---|---:|
| 请求 Paper | 24 |
| lineage entity Paper | 19 |
| Entities | 268 |
| `structure_confirmed` | 268 |
| Complete structures | 268 |
| Missing / non-unique structures | 0 |
| Edges | 242 |
| Explicit edges | 62 |
| Unresolved edges | 180 |
| Pair-ready edges | 62 |
| 有 pair-ready 的 Paper | 18 / 19 |

5 篇没有形成 entity-backed lineage：

- `e04dfea8eedb`：SI 有 1-23 结构，但正文没有唯一直接母体关系。
- `51180402d2ac`：SI 有 3 / 4，但没有支持的 medicinal-chemistry 修改路径。
- `7709b4e1637d`：SI 有 1-16 和 CMX990，正文不足以建立唯一 parent-child。
- `a4380f187553`：正文 DHI / AQ 编号和 SI 5-51 无可靠一一映射。
- `0de5157cf90a`：主要是 natural-product SAR，没有唯一直接母体证据。

Batch 03 的结构修补已达到 `268 / 268`。现在的主要限制不再是
SMILES 覆盖，而是 180 条 series-level 记录缺少唯一 immediate
parent。所有 62 条 explicit / figure edge 都已 pair-ready。Batch 03
继续采取宁可 unresolved，也不为了补数量伪造 pair 的原则。

### Batch 04

| 指标 | 数量 |
|---|---:|
| 请求 Paper | 24 |
| lineage entity Paper | 24 |
| Entities | 559 |
| `structure_confirmed` | 555 |
| Complete structures | 555 |
| Missing / non-unique structures | 4 |
| Edges | 530 |
| Explicit edges | 127 |
| Unresolved edges | 403 |
| Pair-ready edges | 127 |
| 有 pair-ready 的 Paper | 24 / 24 |

Batch 04 已完成所有可唯一表示结构的修补：`555 / 559`。剩余四条
是明确的多组分 racemate 或变量 R-group 通式，不是普通漏提。24 篇
Paper 都已有 pair-ready edge，127 条 explicit / figure edge 全部
pair-ready。

## 五、Batch 04 结构修补状态

### 1. 发布结果

修补清单位于：

`source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch03_04_repairs.py`

其中包含：

- 29 条逐条 source-reviewed complete-graph reconstruction。
- 4 条 external-identifier-backed structure，全部属于
  `9b9e5d0c40bc`。
- 每条都先进入 `compound_structure_work.csv`，再经过结构绑定、
  RDKit 和 confirmation gate 发布到 authoritative confirmed 表。

最新发布输出：

```text
published=33
work_rows=3895
confirmed_rows=2146
```

### 2. `9b9e5d0c40bc` 的重点重建

该 Paper 的 Figure 1 引用了多个历史化合物，单靠当前论文图片难以获得
稳定机器可读结构。本轮用当前 Figure 与原始文献/外部标识符双重
绑定：

- compound 2：Gilleran compound 2 = Matralis compound 5 = Tsagris
  compound 23；ChEMBL `CHEMBL4286841`。
- compound 3，ML-10：RCSB PDB `5EZR`，chemical component `4ZS`。
- compound 4，MMV030084：PubChem CID `22185475`。
- compound 5，RY-1-165：RCSB PDB `8EM8`，chemical component `WLK`；
  保留来源编码的 `(R)` 手性。
- compound 6：与 Eck et al. 2022 Figure 1 compound 3 为同一结构；
  重建的 isoxazole / aminopyrimidine / `(R)`-aminopyrrolidine 完整图经
  RDKit 校验，分子式为 `C23H21ClN6O4S2`。

与论文 Scheme 直接绑定的 `10g`、`11a`、`11g`、`58`和 `61` 也以完整
SMILES 发布。

旧 annotation 曾把 `7a-7e`、`8a-8d`和 `9a-9h` 中的系列成员折叠成源 SI
中不存在的裸编号 `7`、`8`、`9`。三个虚假 placeholder entity 和对应
unresolved edge 已删除，没有任意改绑为某个 `a` 化合物。

### 3. 剩余四个 Batch 04 `--`

Batch 04 的结构补齐从 `470 / 570` 改善到 `555 / 559`。当前四个保留
`--` 的记录均有明确原因：

| Paper | Compound | 质量边界 |
|---|---|---|
| `9b9e5d0c40bc` | `40` | SI 编码为两个立体组分的 racemate，不能任意选取其中一个。 |
| `9b9e5d0c40bc` | `41` | SI 编码为两个立体组分的 racemate，不能任意选取其中一个。 |
| `cda62beb2e03` | `39` | 变量 `R2` 通式，不是唯一完整分子。 |
| `cda62beb2e03` | `41` | 变量 `R2` 通式，不是唯一完整分子。 |

全 aggregate 还有一条 Batch 01 的 `3725c30c81e3 / 1`，它是变量
`R/R′` quinazoline-pyrimidine 通式。因此五条 `--` 都不应被用一个
主观选择的单组分 SMILES 覆盖。

### 4. 保留的结构确认安全边界

- 主体有机分子 + 对离子可以在来源明确时做可审计 component
  selection，但多个立体组分共同定义的 racemate 不可按盐处理。
- Figure / Scheme 重建必须保留 source locator、R-group assignment、
  attachment mapping 和手性判定。
- 编号相邻、scaffold 相似和 RDKit parseability 不能单独作为 parent
  关系或 `structure_confirmed` 的依据。
- 最终 pair 的分子图只能由确认的完整 SMILES 重绘，论文截图只作为
  evidence locator。

## 六、代码与测试状态

本轮的关键生产代码/数据生成器修改包括：

- `source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/lineage_structure_reconstruction.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch03_04_repairs.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/generate_lineage_batch_04_annotations.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/generate_lineage_batch_05_annotations.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_component_selections.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_duplicate_source_repairs.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_prior_art_repairs.py`
- `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`
- `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

新增回归覆盖：

- `9b9e5d0c40bc` compounds 2-5 的 external identifier 绑定。
- compound 2 与 Tsagris compound 23 的完整 thiazole graph。
- compound 6 与 Eck compound 3 的 isoxazole graph 及 `(R)` 手性。
- 不得将中间体系列折叠为裸编号 `7/8/9`。
- Prime label `26a` / `26a′` 必须生成不同 entity，不得产生
  self-loop。
- Batch 05 严格 CSV label header、wrapped-row 以及 GB18030 中文
  header 解析。
- `c6fdd5c7e071` 不得生成来源中不存在的裸标签
  `43/47/53/55`。
- 盐/溶剂组分选择只允许已审阅的 chloride/formic-acid 模式。
- `5531836ee3c3` 重复来源修补只限结构完全一致且保留主表
  row locator 的 `i15/i16/i19`。
- Batch 05 prior-art 修补必须使用精确外部标识符或可定位的
  Paper/SI 完整结构图。

发布、annotation 重生成和 aggregate rebuild 已执行。最新完整验收：

```text
lineage tests:   293 passed in 6.40s
Dashboard tests: 69 passed in 495.17s
```

Dashboard 测试需要从项目根目录使用 `PYTHONPATH=.` 启动。最初仅将
lineage scripts 目录设为 `PYTHONPATH` 时，测试在 collection 阶段无法导入
`dashboard`；这是测试启动环境问题，不是 Dashboard 逻辑失败。

最新 aggregate 完整性审计：

```text
self-loops:                    0
duplicate directed edges:     0
unresolved pair-ready edges:  0
dangling entity references:   0
invalid pair endpoints:       0
```

## 七、当前 aggregate 快照

这是 Batch 05 发布、结构修补和全量 rebuild 后的快照：

- Corpus Papers：672。
- Lineage Papers：114，剩余 558 篇未进入 lineage。
- Lineages：169。
- Compound entities：3,117。
- Lineage edges / evidence rows：2,987 / 2,987。
- Activity rows：620。
- Relation status：`text_explicit=1,387`、`figure_explicit=73`、
  `unresolved=1,527`。
- Complete structures：3,106。
- `structure_confirmed`：3,105。
- Missing / generic / non-unique structures：11。
- Pair-ready edges：1,458。
- 有 pair-ready edge 的 Paper：112 / 114。

完整结构数比 `structure_confirmed` 多 1，是因为一条旧结构仍保持
`model_visual_match_confirmed`。它没有被误报为新的 authoritative
`structure_confirmed` 记录。

## 八、关键文件

### Aggregate 与结构工作

- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_entities.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_edges.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_evidence.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_structure_work.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/confirmed_compound_structures.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_manifest.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_snapshot.json`

### Scripts 与 annotations

- `source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/lineage_structure_reconstruction.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch03_04_repairs.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/generate_lineage_batch_04_annotations.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/generate_lineage_batch_05_annotations.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_component_selections.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_duplicate_source_repairs.py`
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_prior_art_repairs.py`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/`

### Dashboard

- `dashboard/server.py`
- `dashboard/app.js`
- `dashboard/index.html`
- `dashboard/styles.css`
- `dashboard/tests/test_dashboard_server.py`

### 进度和设计文档

- `docs/lineage_batch_progress_2026-09-09.md`
- `docs/lineage_batch_05_2026-09-09.md`
- `docs/lineage_batch_03_2026-09-08.md`
- `docs/lineage_structure_reconstruction_2026-09-08.md`
- `docs/plans/2026-09-08-lineage-structure-reconstruction-design.md`
- `docs/plans/2026-09-08-lineage-structure-reconstruction.md`

## 九、后续顺序

Batch 03 / 04 / 05 的完整结构修补已在“来源定义唯一单分子”
的边界内完成。如果继续深化或开始下一批，顺序应为：

1. 优先复核 Batch 03 的 180 条和 Batch 04 的 403 条 unresolved-parent
   记录，只在正文、Figure、Scheme 或 Table 明确给出直接修改关系时
   升级为 pair。
2. 如果产品需要展示 compounds 40/41 这类 racemate，应先扩展数据模型，
   将“报道化合物”与“组分结构集合”分层；不应用一个单分子 SMILES
   覆盖原记录。
3. 逐条复核 Batch 01 中唯一的 `model_visual_match_confirmed` 结构，决定
   是否有足够 source-backed evidence 升级为 `structure_confirmed`。
4. 继续使用 Dashboard 检查 pair 两端的完整分子重绘、evidence locator
   和 activity，不使用论文结构截图作为最终分子图。
5. 开始新数据发布前重跑完整测试和 aggregate 完整性审计：

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  pytest -q source_pdfs/分子修改提取_2024_JMC/tests

PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py
```

## 十、Batch 05 完成状态

- 24 / 24 篇已生成 Paper-local annotation JSON 并进入 aggregate。
- Batch 05 共有 965 个 entity、946 条 edge；190 条为 explicit /
  figure-supported，756 条保守标记为 unresolved。
- 959 / 965 个 entity 已完成唯一完整结构确认，190 条显式关系
  全部 pair-ready；23 / 24 篇至少有一条 pair-ready edge。
- 剩余 6 条均来自综述 `23fa35c9b113`，是 variable-R family 或不具备
  足够完整图来源的 review-level example，正确状态为 `--`。
- 不进行没有 source-backed evidence 的 parent 推断。
- 不把仅有 RDKit parseability 的 candidate 直接标记为 `structure_confirmed`。
- 不把未检查的 PDF / PDB 作为已完成结构来源。

## 十一、Batch 06 完成状态（2026-09-10）

用户要求继续下一个固定批次，并维持 `7a695794fc7b` 的标准：先从主文和
SI 确认 root template、immediate parent 和 derived compound，再进行完整
结构绑定、R-group/组分判断、SMILES/RDKit 校验和统一分子对重绘。

本批 24/24 篇均生成 Paper-local annotation JSON 并进入 aggregate：

```text
Batch06 Papers:                   24
Compound entities:            1,184
Lineage edges/evidence:       1,157 / 1,157
text_explicit:                   93
figure_explicit:                361
unresolved:                     703
confirmed complete structures: 1,020
missing/non-unique structures:  164
pair-ready edges:               280
Papers with pair-ready:          21
```

独立来源审计后进行了三项关键修正：

1. 修复 `1994543a9112` 的 ISO-8859/CP1252 重复表头 CSV。旧解析会选中
   后续更宽表头并丢弃前段；现在保留全部 38 行（36 个 paper-local
   compounds 加两个对照），恢复 `24a-24e、58a-58c`，并忽略重复表头。
2. 将 `feef9e819b88` 的排除范围由机械的 48 条改为化学上正确的 44
   条；无手性中心的 `A4、D15、D16、D17` 恢复为确认完整结构。
3. 新增精确 source-mismatch 撤回机制。`1994543a9112 / 58c` 的机器图
   错误复制 `58b`，`56f50284cedf / 7-31B` 的机器图与论文的
   4-methylcyclohexyl regioisomer 不符；两者均保持 `--`，原因固定为
   `source_structure_mismatch`，不会被 RDKit 可解析性覆盖。

其余重要边界：

- `434e5748f070` 的 1-44 为 racemate/diastereomer mixtures，保持 `--`。
- `1994543a9112` 的 22 个 epimer-mixture compounds 保持 `--`；`24b`
  为未经精确组分决策的多组分 source row，也保持 `--`。
- `56f50284cedf` 的八个来源明确 racemic/mixture labels 保持 `--`。
- `07dcad0214c3 / 1` 为 racemate，分离的 `2/3` 保持确认。
- `bf54bac4775b` 的 22 个 arbitrary/non-unique stereo rows 保持 `--`。
- `023145d60eea` 的 37 个 SMIP rows 只移除 disconnected `[Br-]`，保留
  有机阳离子电荷和共价 Br；`SMIP-30` 无精确来源 row，保持 `--`。

最终 aggregate：

```text
Corpus Papers:                  672
Lineage Papers:                 138
Remaining Papers:               534
Lineages:                        193
Compound entities:             4,301
Lineage edges/evidence:        4,144 / 4,144
Activity rows:                   620
Complete structures:           4,126
structure_confirmed:           4,125
Missing/non-unique:              175
Pair-ready edges:              1,738
Papers with pair-ready:          133
```

最终验证：

```text
lineage/structure tests: 311 passed in 7.90s
Dashboard tests:          69 passed in 654.97s
self-loops:                              0
duplicate directed edges:               0
unresolved pair-ready edges:            0
dangling edge/evidence references:      0
invalid pair endpoints:                 0
```

Dashboard 中的结构图继续只由确认完整 SMILES 经 RDKit 统一重绘；来源文章
截图只作为 evidence locator，不作为最终 pair 分子图。
