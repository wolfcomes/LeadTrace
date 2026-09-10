# 2024 JMC 分子修改提取

这个目录只保存从 `文章收集` 中的 JMC Volume 67（Issue 1-22）PDF 生成的中间结果和审阅结果，不复制或修改原始论文。

## 阶段目录

- `01_manifest`：原始 PDF 的可追溯清单，以及固定的试运行样本。
- `02_text_extraction`：PDF 文本层、页码和可解析性索引。
- `03_sar_candidates`：自动识别的候选 SAR/结构修改证据。它们尚未被认定为正确的化学关系。
- `04_path_candidates`：将每条候选修改陈述转为“母体/先导化合物 -> 衍生物”路径记录；没有明示化合物对的行保留原文，待 Scheme 或表格复核。
- `04_review`：试运行统计、失败清单和供人工复核的说明。
- `05_visual_review`：高置信度路径的证据页 PNG，以及其余路径的 Scheme/表格复核优先级队列。
- `06_text_confirmed_paths`：正文已经明确支持的唯一路径，等待结构图确认与 SMILES 补全。
- `07_enriched_text_paths`：从更严格的“引入取代基得到新化合物”等句型中补出的有向路径；均须经结构图复核。
- `08_ocsr_benchmark`：结构 crop 清单、DECIMER proposal 及其 RDKit 校验结果；proposal 不能直接视为确认结构。
- `09_structure_confirmation`：16 条显式路径的 SI SMILES 参考、RDKit canonical SMILES 和统一生成的 parent/derived/path PNG；仍需人工确认后才能进入最终路径数据集。
- `09_paper_review/auto_fill/first_page_fragment_review.csv`：按 manifest 前 20 篇 Paper 整理的图片优先结构审阅快照。它先标注非结构区域、片段/系列、完整分子候选和混合区域，再记录连接点推理与 SMILES/RDKit 语法状态；proposal 仍需人工确认。
- `09_paper_review/auto_fill/first_page_molecule_objects.csv`：在上述图片候选之下继续拆分出的分子对象层。只保留编号分子、共享骨架、替换片段、可变位点、linker 和包含化学结构的混合区域；明确的图表、文字、蛋白场景和 3D-only 区域在 object 生成时直接过滤。保留的 object 都有独立对象 ID、局部 bbox、局部 crop、连接位点和 SMILES 资格状态；未完成结构推理时使用 `--`，不把页面级 OCSR 结果复制到对象上。
- `09_paper_review/auto_fill/molecule_review_crops`：对象层局部证据图，仅由原始候选 crop 裁切生成；最终分子主视觉仍应由确认后的 SMILES/RDKit 统一生成。
- `09_paper_review/auto_fill/compound_entities.csv`：Paper 内去重后的化合物实体。每个实体记录名称/编号、root/lead/intermediate/derived 角色、完整结构状态、SMILES、结构来源和匹配到的完整分子 object。
- `09_paper_review/auto_fill/compound_lineage_edges.csv`：药化修改迭代链的有向边。每条边分别记录根母版、当前轮直接母体、衍生化合物、修改位点、关系证据状态和 pair 资格；同图从属、编号相邻和结构相似不能单独确认边。
- `09_paper_review/auto_fill/compound_lineage_evidence.csv`：逐条 lineage edge 的正文、Figure、Table 或 Scheme 证据，保留页码和原文，不与 SMILES 置信状态混合。
- `09_paper_review/auto_fill/compound_activities.csv`：按化合物和 assay 拆分的活性数据，可用于显示每轮 parent-to-derived 活性变化。
- `09_paper_review/auto_fill/lineage_annotations/`：按 Paper 保存的可审计 lineage 注释；批次之间只写各自的 JSON，最后由 builder 统一合并，避免并行任务覆盖总表。
- `scripts`：可重复运行的提取脚本。

## 当前试运行的边界

`scripts/run_pilot.py` 从五个期号文件夹中各抽取六篇，共 30 篇 PDF。它会提取：

- DOI、页数和文本层可读性；
- 涉及 compound/analogue/derivative 的活性陈述；
- 涉及 substitution/replacement/introduction/optimization 等词的候选修改陈述；
- 每条候选的源 PDF 绝对路径和页码。

此阶段不把结构图自动转成 SMILES，也不推断未经人工检查的“化合物 A 到化合物 B”的真实结构差异。正文 PDF 中的 Scheme 和表格需要在下一阶段结合图像/结构解析复核；完整合成路线还需要 Supporting Information。

## 运行方式

在工作区根目录运行：

```powershell
python '文章收集\分子修改提取_2024_JMC\scripts\run_pilot.py'
```

处理完整 672 篇，并建立所有文本证据支持的修改路径候选：

```powershell
python '文章收集\分子修改提取_2024_JMC\scripts\run_full_paths.py'
```

生成 Scheme/表格复核队列和高置信度路径的证据页：

```powershell
python '文章收集\分子修改提取_2024_JMC\scripts\prepare_structure_review.py'
```

补充提取正文中以“在先导上引入/替换后得到新化合物”表达的路径：

```powershell
python '文章收集\分子修改提取_2024_JMC\scripts\enrich_text_paths.py'
```

根据 Supporting Information 为 16 条显式路径生成统一的 SMILES 分子图：

```powershell
python '文章收集\分子修改提取_2024_JMC\scripts\structure_confirmation.py'
```

生成的分子图只使用 SI 中的 SMILES 和 RDKit；文章页面 PNG 只作为来源证据，`08_ocsr_benchmark/crops` 只作为 OCSR 输入。

第一页结构对象层可重复生成：

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  python source_pdfs/分子修改提取_2024_JMC/scripts/build_first_page_molecule_review.py
```

该脚本执行顺序是“图片区域定位 -> 编号/骨架/片段拆分 -> 连接位点保留 -> 单对象 OCSR 资格判断”。它只写入 `09_paper_review/auto_fill/`，不会修改原始 PDF、页面级候选、正文路径或已确认结构。

对已完成局部隔离、可进入 OCSR 的对象运行 proposal 批处理：

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  .venv-jmc-ocr/bin/python source_pdfs/分子修改提取_2024_JMC/scripts/run_first_page_molecule_ocr.py
```

该批处理不会把 `R`、`Site`、`Linker` 或非结构区域送入 OCSR；`rdkit_status=valid` 只说明字符串语法可解析。模型输出中的多组分、金属/异常原子和过长字符串会保留原样，并标记为 `valid_but_suspicious_needs_review`。`heuristic_primary_component_smiles` 只是最大主组分的人工核对辅助字段，不能替代结构图推理或人工确认。

生成药化修改迭代链：

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  python source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py
```

生成顺序是“识别 root template -> 确认直接 parent/derived 关系 -> 绑定完整结构来源 -> 绑定活性记录 -> 判断完整 pair 资格”。Builder 会同时读取 `lineage_annotations/` 和 `09_structure_confirmation/confirmed_path_structures.csv`；后者提供已经由 SI SMILES 支持的高质量种子路径，逐篇 JSON 注释可覆盖或补充它们。没有上游 root 证据的独立明确路径暂以 direct parent 作为 root template，并在 annotation note 中记录这一保守默认。

Objects 中的 `parent_object_id` 只表示图片内的骨架/片段从属关系，不会进入 lineage。只有关系明确且 parent/derived 都具有完整可解析 SMILES 的边，才会在 Paper 详情的统一审阅区显示为完整 molecule pair；关系未解或结构缺失的边仍保留为 `--` 状态，不生成伪结构图。汇总文件中的 `lineage_paper_ids`、`pair_ready_paper_rows`、`corpus_paper_rows` 和 `remaining_corpus_paper_rows` 用于记录批处理进度。
