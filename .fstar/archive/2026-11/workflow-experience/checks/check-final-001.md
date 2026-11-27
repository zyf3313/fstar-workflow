# check-final-001：独立最终检查（失败，已进入修复）

- 检查角色：独立 fstar-check；read_only: true；changed_paths: []。
- 基线：分支 feat/workflow-experience，HEAD 3acd9ce94a374f110dc3519cdfe6d2d3a610ec77；399 个输入起止哈希相同，基线清单 `/tmp/fstar-check-final-001-baseline.json` 的 SHA256 为 `5bedd3ee9deb23234a38c026a69dd6004382941c0e7c60a6d7b852173d4f0e99`。这是本次检查基线，后续计划文档修正会使其过期。
- 结果：failed。plan.md 未具体引用适用规范，且错误称设计调查未完成；需修正并以新基线重新做最终检查。
- 对照：理解以 clarify.md 中记录的用户原话为依据；一致性发现上述计划缺陷；交付可用性仅在已测确定性范围有证据，真实宿主语义行为仍有缺口。

| 判据 | 结论与依据 |
|---|---|
| A-001 | 未验证：自然识别触发、归档复盘及最终集成宿主中的非阻塞行为没有端到端证据。自动审批曾拒绝外部宿主模型测试，不能把指令存在等同于行为通过。 |
| A-002 | 已测确定性范围通过：worktree、存储与冲突保护测试；非协作写入、崩溃一致性和全部历史数据兼容未验证。 |
| A-003 | 已记录的范围分流及确定性桥接测试通过；语义候选分类未验证。 |
| A-004 | 失败：本任务计划缺少具体规范引用，状态过时。 |
| A-005 | 整体未验证：角色协议和历史缺卡阻断有证据，最终集成宿主的自然使用与记录未验证。 |
| A-006 | 确定性加载、来源绑定和诊断测试通过；整体未验证，worker 自报回执不能证明实际读取。 |
| A-007 | 整体未验证：有确定性保护测试，但未建立所有范围内步骤的完整清单和真实宿主执行证据。 |
| A-008 | 部分通过：资源清单 64/64 指纹匹配；协调方全量 Python 1105 项和 Node 16 项通过，日志未绑定完整输入指纹；独立定向 201 项通过。影响和宿主语义覆盖仍不完整。 |

- 独立验证：临时 HOME、FSTAR_USER_ROOT、FSTAR_RUNTIME_ROOT、TMPDIR；`PYTHONDONTWRITEBYTECODE=1`。运行 `python3 -m unittest tests.test_installer tests.test_dispatch_context tests.test_worktree_identity tests.test_user_procedure_scope tests.test_planning_contract tests.test_worker_hook_failure`：201 项，34.571 秒，OK；日志 `/tmp/fstar-check-final.7MKn7U/tests.log`。清单散列与版本一致，`git diff --check` 通过。检查总耗时 235.03 秒，重试 0。
- 协调方全量日志：`/tmp/fstar-final-regression.DMbxckSz/python.log`（1105 项 OK）、`/tmp/fstar-final-regression.DMbxckSz/node.log`（16 项通过）。此前 install 退出 2 缺少完整原始命令及 stderr，重建后安装测试通过，但原失败原因不能确定。
- 未运行：外部模型、Herdr、真实安装、竞争及断电测试、全部历史迁移。没有调用外部模型或改动真实用户数据。
