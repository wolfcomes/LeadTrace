# AI_prefill 交付检查索引

流程 `deepseek-led-v3-20260923`。每项记录检查者、实际范围、证据和 `pass / fail / uncertain / not_applicable`；尚未检查为 `not_checked`。本表是简短交付索引，不是额外 validator，也不重复科学规则。

| 项目 | 交付检查 | 权威细则 |
|---|---|---|
| 任务身份 | 外部 task/catalog、实际源、input、candidate、目标 Preview 一致；hash/bytes/pages/DOI/题名有来源 | [运行指南](deepseek-supervised-runbook.md#输入包与最小阅读) |
| Compound 范围 | 源清单完整身份、required＋all-inventory、缺失/歧义/排除；未决不删分母，不按编号补造 | [收录范围](extraction-guide.md#compound-catalogue-scope) |
| 结构 | 从源确定核心连接/稠合；重新读最终保存结构，核对全体变体映射/重绘及立体、化学形式；代表修好不代表全族已修 | [提取流程](extraction-guide.md#workflow) |
| 原图 | 自身 locator 含核心＋编号行＋所有定义；实际裁图视觉核对，参考物缺图诚实说明 | [提取流程](extraction-guide.md#workflow) |
| 测量 | 全部可用源测量清点与 tuple 匹配；准确率和覆盖分开，剂量/条件/误差/单位/ND 正确 | [自检七项](deepseek-self-check-guide.md#先程序检查再源核查) |
| 关系 | SAR/合成分开，真实端点/直接与多步/共同反应物/AI 推断限制；缺引文不自动否定 | [提取流程](extraction-guide.md#workflow) |
| Lineage | 源事件/比较→逐边映射与遗漏，逐组角色/分量处置，每个 Compound 双类型参与，优选独立；账本完整不等于科学确认 | [分组规则](extraction-guide.md#lineage-grouping-roles-and-participation) |
| 修订保留 | 精确 parent、变更/依赖范围、有效审查继承、未受影响数据/人工编辑保留、无意外差异 | [运行指南](deepseek-supervised-runbook.md#已有候选自检修补入口) |
| 自检 | 最终文件 hash、七项实际检查、确定问题/未决、真实 edge refs；局部检查不冒充全篇 | [自检交付](deepseek-self-check-guide.md#最终绑定与交付) |
| 简化提示 | 有依据的完整候选存在具体不确定/冲突时写 review_hint；统一 ⚠，不分级；无可推导结构不收录，已知错误不能用提示掩盖 | [推导与提示](extraction-guide.md#source-supported-inference-and-simple-review-hints) |
| 问题闭环 | 反馈→实际字段差异→源核验→依赖结论；明细与声称修复数相符；未改/新增/撤回均有处置 | [最终产物闭环](deepseek-self-check-guide.md#最终产物与问题闭环) |
| 独立审查 | 新上下文、冻结范围/样本、逐字段 C/E/U 与 N/P；结构/值/条件/出处/依赖分开，结论和理由一致；误报也须核对 | [审查协议](quality-audit-protocol.md) |
| 调用与停止 | 基线生成＋独立检查；必要修补＋新复核是另两次调用；未查、提取失败、缺源/歧义、审查争议分开 | [调用边界](deepseek-supervised-runbook.md#日常调用边界与停止条件) |
| 交付 | 真实状态/usage/会话/下一步；受信操作者处理 Preview 授权、实例/版本、快照和真实回执 | [运行指南](deepseek-supervised-runbook.md#preview-与跨任务交付) |

科学结论绑定精确内容和源依赖，任何修改后检查旧结论是否仍适用。未知保留未知；不以“exit 0”“有图”“新 AI 说全部正确”代替检查。重复失败或预算耗尽保存 partial/未决，不降标准、不无限返工。常见触发风险见 [质量问题](quality-pitfalls.md)。
