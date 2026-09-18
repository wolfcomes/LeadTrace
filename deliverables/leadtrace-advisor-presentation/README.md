# LeadTrace 导师汇报版

这套 12 页演示文稿面向导师或课题组汇报，建议时长 10–12 分钟。主线不是逐项展示功能，而是说明 LeadTrace 如何把药物化学论文中的结构、优化关系、原始证据和活性数据，转化为可信、可审核、可供后续计算使用的研发知识。

## 文件

- `LeadTrace_导师汇报版.pptx`：PowerPoint 版本，12 页，16:9。
- `LeadTrace_导师汇报版.pdf`：便于预览和发送的 PDF 版本。
- `preview.png`：全套页面缩略图。
- `SPEAKER_NOTES.md`：逐页讲稿，可直接用于 10–12 分钟汇报。
- `rendered/`：每页 1600×900 PNG，可用于快速替换或单页分享。
- `rendered/manifest.json`：源文件与渲染结果的 SHA-256 绑定，用于检测过期产物。
- `source/presentation.html` 与 `source/styles.css`：可编辑的内容和视觉源文件。
- `source/render.mjs`：使用 Playwright 生成页面图片。
- `source/package_presentation.py`：生成 PPTX 与 PDF。
- `source/verify_presentation.py`：结构、尺寸、页数和关键内容检查。

PPTX 采用高保真整页画布，视觉结果与 PDF、PNG 一致。文字或布局调整应在 HTML/CSS 源文件中完成后重新生成。

## 建议讲述节奏

| 页码 | 建议时间 | 讲述重点 |
|---:|---:|---|
| 1 | 40 秒 | 一句话定位：把药化论文变成可计算、可追溯的研发知识。 |
| 2 | 55 秒 | 痛点不只是 PDF 非结构化，而是“修改—活性—证据”决策链会丢失。 |
| 3 | 55 秒 | 研究命题：可信科学 AI 需要知识生产闭环，不只是单次抽取。 |
| 4 | 70 秒 | 解释 Paper、Compound、Structure、Lineage、Edge、Evidence、Activity 的关系。 |
| 5 | 70 秒 | 从只读来源到管理员发布；重点讲工作流边界与不可变提交。 |
| 6 | 70 秒 | AI 负责预填，专家负责定责；用竞争场景说明系统不会覆盖人工成果。 |
| 7 | 60 秒 | 展示真实工作区：PDF、结构编辑、RDKit 回显、谱系和证据在同一上下文。 |
| 8 | 65 秒 | 可信性如何落到来源、历史、快照、哈希、备份与恢复，而不是口号。 |
| 9 | 50 秒 | 快速说明内网架构、PostgreSQL 权威、Worker 和只读 Source PDF。 |
| 10 | 80 秒 | 用真实试点数字证明闭环已经运行；明确这是隔离试点，不是生产规模。 |
| 11 | 70 秒 | 从当前贡献自然过渡到跨论文 SAR 网络与 AI-ready 研发底座。 |
| 12 | 35 秒 | 收束为“组织研发记忆”，然后进入提问。 |

## 三句话版本

如果汇报时间被压缩，可以只保留这三句话：

1. 药物化学论文保存了结果，但没有把结构修改、活性变化与证据依据变成可计算的决策链。
2. LeadTrace 通过 AI 预填、专家核验、管理员审批和不可变发布，把这条决策链生产成可信知识资产。
3. 20 篇论文完成确定性入库，3 个代表性工作区验证了人工、AI 与并发保护流程，其中 2 个形成正式发布版本；审计与恢复门禁同步通过。

## 证据边界

- 可以表述：可信科学数据生产平台、Human-in-the-loop 知识工厂、药物化学知识操作系统的雏形。
- 已验证：20 篇隔离试点、人工与 AI 工作流、竞争保护、不可变提交、发布、审计、备份和恢复。
- 不应表述：已经完成生产规模部署、已经证明显著缩短药物研发周期、AI 能够全自动准确抽取所有论文、跨论文推理已经上线。
- 第 10 页的测试与恢复数字来自 `docs/acceptance/leadtrace-paper-centric-pilot-results.md`。

## 重新生成

在仓库根目录运行：

```bash
node deliverables/leadtrace-advisor-presentation/source/render.mjs
python deliverables/leadtrace-advisor-presentation/source/package_presentation.py
python deliverables/leadtrace-advisor-presentation/source/verify_presentation.py
```

渲染依赖 `leadtrace/frontend/node_modules` 中已安装的 Playwright，以及当前 Python 环境中的 Pillow、python-pptx、ReportLab、lxml 和 PyMuPDF。
