# DeepSeek 交付前自检指南 v1

适用于 supervised-v2 提取之后。自检由提取者完成，目的是先修掉可发现的错误、减少独立审查返工；不是独立审查，更不能自行批准 Preview。保留原始提取候选，不修改历史实验的冻结指南或报告。

## 必须交付什么

1. 最终 `candidate.json` 与独立调查阶段冻结的 `compound-inventory.json`。
2. 现有的 `measurement-inventory.json` / `measurement-coverage.json`、`structure-verification.json`、`route-details.json`、`quality-record.json`。
3. 按 [模板](templates/deepseek-self-review.json) 填写 `self-review.json`，再运行程序生成 `self-check.json`。不要向 CandidateEnvelope 添加自检字段。
4. `self-check-notes.md`：修正了什么、改动影响哪些结构/表/边、尚未解决什么、实际检查范围。自检前副本使用 `candidate-before-self-check.json`；自检修订差异单独保存。已经正式交付的候选若要修订，仍遵循 parent/evaluation 链，不能覆盖已登记ID。

## 执行顺序

监督者提供绝对工作目录、Python和repo路径。以下命令从工作树根目录执行；生产者只访问本任务输入和已安装模块，不读取Preview账号、数据库或其他论文答案。

```bash
PYTHONPATH=/absolute/worktree /absolute/worktree/.venv/bin/python -m leadtrace.ops.ai_prefill candidate self-check \
  /absolute/job/candidate.json --inventory /absolute/job/compound-inventory.json \
  --output /absolute/job/self-check-preflight.json
```

第一次没有 `--self-review`，因此报告 `SELF_REVIEW_MISSING`、退出4是预期行为。先读完整报告，修复确定性问题，再完成下面七项源文自检。不要仅修改状态为checked；必须实际打开相应表格、图或正文并留下位置和检查范围。

完成之后，对最终candidate**文件字节**计算SHA-256，填入self-review；它不同于canonical candidate hash。不要先算hash后继续改candidate。重新生成最终报告：

```bash
PYTHONPATH=/absolute/worktree /absolute/worktree/.venv/bin/python -m leadtrace.ops.ai_prefill candidate self-check \
  /absolute/job/candidate.json --inventory /absolute/job/compound-inventory.json \
  --self-review /absolute/job/self-review.json --output /absolute/job/self-check.json
```

退出0=`ready_for_independent_review`，仅表示此版本已实现的检查通过、源自检声明完整；退出4=`needs_revision`，退出2=输入不合法。程序不访问原文，不能证实自检声明真实。review类提示仍须在notes中解释。即使0，也保留 `supervisor_preview_gate=not_reviewed` 和待人工审查状态。监督者可明确允许带缺陷候选进入Preview供查看；生产者无apply权限。

每项完成立即保存。默认一次系统自检、最多两轮修正并复跑；到时间仍有问题，保存partial与unresolved，不无限重试、不编造补齐、不缩小调查清单以使覆盖通过。

## 七项源文自检

| check_id | 实际检查与记录 |
|---|---|
| compound_scope | 对照冻结清单，包含正文/引言/图中参考物和控制；打印label与解释名称分开。Methods-only中间体留route-local。每个缺失身份解释原因，但不得从分母删除。结构无法确认时将身份及已有测量放入unresolved-items，不猜结构来凑数；当前Candidate契约仍要求结构。 |
| measurement_coverage | 逐表、图注、图中打印数值、正文测量核对。每个观察用compound＋assay/endpoint＋条件＋源位置匹配candidate索引。分开numeric/censored/ND/qualitative/graph-unresolved；>阈值不是ND。表格之外特别检查kinetics、ADME/PK、不同时间点和引言参考物。源未报告与提取遗漏分开。分母未完整核实就不报总体覆盖百分比。 |
| activity_semantics | 检查value/operator/unit/raw token和条件。S.I.等比值无量纲；剂量是条件，ED50/MTD是合法测量终点。±并不自动是SD，保留源明确的SD/SEM/n；源未定义就记录未知。不同时间、物种、配方、给药途径不能并成一条。不要把重复引用当独立实验。 |
| structure_identity | 实际对照最终重绘与源图，检查骨架、环大小/原子、外围末端碳、连接位点、保护基、区域异构、立体构型/混合物/盐形式。所有新加入参考物单独检查。通用药名推得的结构须注明外部身份来源，不能说源图已核准。RDKit通过不证明结构正确。 |
| source_crops | 打开实际裁图，确认每个compound自身的core＋row label＋全部R-group定义都在其locator集合内，无裁掉的甲基/OH/脚注。无原图的对照如实记录；重绘不是原图证据。 |
| sar_reasoning | AI推断可没有text evidence。检查两端、变化和方向是否合理，不因无引文删边，不把编号顺序当优化顺序。checked_edge_refs只能列候选真实ref，不能列虚构分组。 |
| synthesis_paths | 对照scheme和Methods核实真实前体、直接/多步、试剂、温度、溶剂。同一母路线的终产物不自动互为前体；经Methods-only中间体的合法全局多步关系不得漏记。route-local编号要命名空间，避免与正文编号冲突。核对edge与route-details一致；源内不一致具体列出支持来源与未决项。 |

每项状态只能是 `checked / unresolved / not_checked / not_applicable`。`checked`需要实际source_locations；`unresolved`保留受影响label/索引/ref和原因，不算通过。not_applicable需要details解释，不能豁免compound_scope、measurement_coverage、structure_identity；候选已有对应边/活性/裁图时也不能豁免其检查。测量清点未完整完成，应为unresolved，不能以“检查了一个表”交全篇完成状态。

## 程序当前覆盖的范围

已实现：复用schema/引用/结构可解析性验证、required标签缺失/歧义、窄语义给药dose终点、S.I./selectivity ratio单位、同源同条件重复Activity、lineage缺分类、自检缺项/未决/无效豁免、最终文件hash过期、不存在的edge ref。给无活性compound提示，**不把它们自动判为漏提**。SAR无支持Evidence仅review提示，不阻断。

尚未自动实现：原文测量穷尽清点与逐tuple匹配、SD/SEM源支持、糖类立体化学、source crop完整性、合成温度与真实路径判定、任意审查报告的样本统计一致性。以上由源自检和独立审查负责，不得把文件存在或自己填checked当程序验证完成。
