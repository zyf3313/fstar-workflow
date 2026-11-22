<!-- Allowed placeholders: {{run_id}}, {{environment}}, {{delivery_baseline}}, {{duration_retries}} -->
<!-- Required placeholders must be replaced. -->
# 检查报告 {{run_id}}

- scope: incremental | final
- environment: {{environment}}
- delivery baseline: {{delivery_baseline}}
- measured duration / retries: {{duration_retries}}

| 标准 / 要求编号 | 对照内容与版本 | Test path and identifier | Command or review method | Result | Log |
|---|---|---|---|---|---|
| A-001 | 待确认 | 待确认 | 待确认 | not_run | 无 |

Result values: passed, failed, blocked, skipped, not_run.

对照内容与版本列填写所依据的标准编号（criteria.md 条目，注明其版本）及被检成果的版本/指纹，不重写标准原文。

## 三线检查结论

- 理解正确性：是否正确理解目标与用户原话，无遗漏、无擅自增加。
- 符合约定：成果是否符合澄清记录与计划中的约定。
- 交付可用性：用户拿到的交付是否可用、可理解；未验证项单独列出原因。

## 并行拆分与汇总（大任务适用）

按标准条目切分检查范围（不按文件切），各分片为全新检查实例；此处汇总各分片结果、分片编号与受影响标准编号，并对整体负责。只读最终检查不并行。最终检查证据必须带 "read_only": true 且不得有任何 changed_paths（内核在记录时强制，改动过的最终检查会被拒绝并要求重新检查）。

## Repairs and reruns
## Uncovered scope and blockers
