# Preview刷新与交付前自检验收（2026-09-21）

用户明确要求把007/009/020本轮结果写入现有Preview，并把指导规则落实为检查、增加DeepSeek交付自检。科学源文仅由此前DeepSeek核查，本轮Codex未阅读原始论文内容。

## Preview

现有服务健康，三篇均为editing/version2且无人工修改历史。旧initial-prefill接口只接受空白Workspace，故没有重置版本或绕过该接口：通过原有versioned domain编辑服务更新三篇，每篇一个事务，保留before/after快照和逐项ChangeEvent以及preview.candidate_refresh事件。当前工作区版本007=868、009=802、020=314。旧ApplicationReceipt描述旧候选，不能冒充新候选receipt；本轮另存refresh记录。

前几次操作脚本因actor权限、完整model registry和LineageMutation返回字段不匹配而回滚，未提交部分科学数据。修正脚本调用方式后，三篇事务提交成功。没有改变服务权限规则。记录的操作者是分配给这些工作区的Preview Reviewer，更新事件明确标为候选导入操作；不代表人工科学审阅。

- 007：56 compounds /232 activities /69 locators /51 SAR edges /0 synthesis edges。
- 009：35 /251 /56 /23 SAR /24 synthesis。
- 020：24 /39 /68 /21 SAR /4 synthesis。
- 115个结构均draft；全部边draft；193个source locator均ready。
- 数据库snapshot hash与提交记录相符；数据内容的结构、Activity value/operator/unit/context/evidence、edge端点/type/summary与冻结候选相符。
- 全部重绘与裁图资源经资产路径映射、hash验证及登录Reviewer HTTP读取验证；局域网页面与API可访问。未通过视觉阅读原图做科学验证，也未声称本轮浏览器交互自动化覆盖。
- 原始候选文件hash未变；before快照及已知问题另存。待修订的科学问题按原样进入Preview供查看，没有静默修复后重算实验效果。

运行记录位于 `leadtrace-data/deepseek-last3-v21-20260920/preview-20260921/`，包含apply.py、各篇before/after/result、verification.json、payload-verification.json。

## 自检实现

新增offline `candidate self-check --inventory ... [--self-review ...] [--output ...]`，模块assistance_self_check.py；不改变既有validate和Preview API。

复用契约验证/compound覆盖，新增dose终点、selectivity ratio单位、同源同条件重复Activity、lineage未分类，以及self-review缺失/缺项/未决/过期hash/无效豁免/不存在edge ref检查。无活性身份给review提示，缺text evidence的SAR仅review提示。source review七类：compound scope、measurement coverage、activity semantics、structure identity、source crops、SAR、synthesis。

生成报告包含最终文件hash与canonical candidate hash、逐项issues、scope限制；退出0只ready_for_independent_review，4表示待修订或自检未完成，2为非法输入。scientific_approval始终false，whole_population_accuracy始终null。程序不读原文，不能验证自检陈述真实；测量tuple清点、源支持的SD/SEM、结构/路径/条件仍为源审查责任。

新增指南deepseek-self-check-guide.md与模板templates/deepseek-self-review.json，接入supervised runbook、task prompt、quality checklist、CLI README。后续派发必须复制并hash新文件；本轮历史bundle不修改。默认一次源自检、最多两轮修正，保留自检前版本，未决交partial，不能自己批准Preview。

## 测试与真实数据回归

新增测试先运行确认9项失败（尚无CLI命令/模块），实现后通过；补充合法无证据SAR、无效豁免、不同条件不误判重复等用例。

最终命令（worktree/leadtrace/backend）：

```bash
../../.venv/bin/python -m pytest tests/ops/test_ai_prefill_self_check_cli.py tests/ops/test_ai_prefill_coverage_cli.py tests/ops/test_ai_prefill_cli.py tests/ops/test_ai_prefill_cli_smoke.py tests/ai_prefill/test_assistance_validation.py -q
```

结果44 passed。git diff --check通过。真实冻结候选只读回归：007检测5条dose与PMX53缺失；009检测19条S.I.单位错误；020检测compound2缺失。三篇未运行新的DeepSeek自检，故SELF_REVIEW_MISSING为预期阻断，不伪造自检报告。结果位于实验目录self-check-20260921/summary.json。

尚未运行新的提取/自修实验，因此不能宣称这份新自检指南已经提高最终科学准确率；当前证据是程序对已知错误的检出和兼容性测试。
