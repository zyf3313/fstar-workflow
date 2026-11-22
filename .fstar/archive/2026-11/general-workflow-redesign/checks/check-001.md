<!-- Allowed placeholders: {{run_id}}, {{environment}}, {{delivery_baseline}}, {{duration_retries}} -->
<!-- Required placeholders must be replaced. -->
# 检查报告 check-001

- scope: incremental
- environment: macOS (Darwin 27.0.0), python3, node --test；分支 chore/general-workflow-design 工作区未提交改动
- delivery baseline: 工作区未提交改动（S-1 实施产出，未 commit）
- measured duration / retries: Python 全量 806 tests 约 104s，1 次运行；Node 16 tests 约 8.5s，1 次运行；build-package 幂等验证 1 次

| 标准 / 要求编号 | 对照内容与版本 | Test path and identifier | Command or review method | Result | Log |
|---|---|---|---|---|---|
| S-1-1 全量测试 | plan.md S-1 完成判据；dispatch S1-check-001 标准 1 | tests/（全量）；tests/test_package.cjs | `PYTHONPATH=src python3 -m unittest discover -s tests -t .` → Ran 806 tests, OK（退出码 0）；`node --test tests/test_package.cjs` → 16 pass / 0 fail（退出码 0） | passed | 本地运行输出 |
| S-1-2 模板与设计一致性 | doc/design.md §2（2026-11-21 draft 已评审）+ samples/ 样稿 | resources/templates/task/{plan,clarify,criteria,check}.md | 对照检查：plan 含 整体思路/步骤/验证与交付/维护/沉淀 五节，步骤条目含 目的/输入/行动/产出/完成判据/遇阻处理/依赖与调整，保留 `<!-- fstar:item:P-001:start/end -->`；clarify 结构与样稿一致（背景原话/事实来源/确认结论/假设未知/取舍/开放问题/被替代结论）；criteria 含五要素（依据/场景与期望/检查方法/证据要求/判定边界）且 A-002 示例与 samples/research/acceptance-flow.md A2 同源；check 含标准编号列（"标准 / 要求编号"）与三线检查结论区 + 并行拆分汇总 | passed | 人工对照 |
| S-1-3 路径迁移完整性 | design.md §2（prd/design 转场景参考） | resources/templates/、src/fstar/content.py、全仓 grep | `resources/templates/doc/` 已删（4 文件）；scenarios/software/ 下 prd/design 及 mapping.yaml 与 HEAD 原文件逐字节相同（diff 确认）；grep src/ resources/ tests/ scripts/ docs/ 无 `templates/doc` 残留（tests 中 "doc/prd.md" 仅为 evidence 快照的任意 artifact 名，与模板路径无关）；content.py TEMPLATES 12 项、路径均存在 | passed | 命令输出 |
| S-1-4 幂等 | dispatch 标准 4 | scripts/build-package.cjs | 运行前记录 git status --porcelain，运行 `node scripts/build-package.cjs`（退出码 0），再比对：无 diff | passed | NO_DIFF |
| S-1-5 越界检查 | dispatch 标准 5 | git diff --name-only | 生产代码改动仅 src/fstar/content.py（且仅 TEMPLATES 常量一行改动）；其余为 templates 资源、package-assets.json（构建产物）、测试；`.fstar/tasks/` 均为未跟踪的任务资料（本检查目录新增），无归档文件改动 | passed | git status/diff |
| S-1-6 manifest 真实性 | dispatch 标准 6 | resources/package-assets.json | 脚本核对 62 个文件条目：全部存在且 sha256 与实际文件一致；模板条目 15 项含新增 criteria.md 与 scenarios/software/ 4 项、无 doc/ 旧条目 | passed | 脚本输出 |

Result values: passed, failed, blocked, skipped, not_run.

对照内容与版本列填写所依据的标准编号（criteria.md 条目，注明其版本）及被检成果的版本/指纹，不重写标准原文。

## 三线检查结论

- 理解正确性：S-1 范围（design §2 模板整改第一步）被准确执行：四份 task 模板重写/新增、prd/design 平移到 scenarios/software/（内容未改动，符合"转为软件场景可选参考"）、manifest 重建。未发现擅自增加或遗漏。
- 符合约定：与 plan.md S-1 完成判据逐条相符（全量测试绿、模板与样稿结构一致、无旧默认生成路径残留）。plan.mapping.yaml 未改动（design §2 将其列为"随重写评估"，S-2..S-6 仍有 P-xxx 条目依赖，保留合理且测试断言 rglob 计 3 个 mapping.yaml 仍通过）。
- 交付可用性：测试与幂等证据可直接复现（命令已记录）；实施者此前报告的 2 项环境性不稳定失败（hooks/installer 类）本轮未出现，806 项全绿，无需区分处理。

## 并行拆分与汇总（大任务适用）

本次为单一检查实例（S1-check-001），无并行分片。

## Repairs and reruns

无修复。检查过程中未发现需要修改测试断言或资源清单同步的问题。

## Uncovered scope and blockers

- 无 blockers。
- 未验证项：S-2..S-6 未实施（不在本次 S-1 范围）；criteria.md 的 artifact_map 式条目提取机制属 design §9 开放问题，本检查仅核对模板内容五要素，未验证 evidence 快照对新模板的兼容（plan.md 的 P-001 条目标记保留，现有 snapshot 机制依赖的语法未破坏，全量测试含 evidence 相关用例均绿）。
- scope 标为 incremental：S-1 为六步切分中的第一步，最终（final）检查待 S-6 完成后另开只读检查。
