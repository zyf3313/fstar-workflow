# runtime-dispatch 联合独立检查报告

日期：2026-10-29。检查者：trellis-check（联合 runtime-dispatch + runtime-hooks 范围）。
解释器：**Python 3.9.6**（`python3 --version` 实测）。项目无 Git 仓库（父目录非 git），无 diff 可查，检查按文件清单直读源码执行。

## 修复的缺陷（全部有回归测试）

1. `src/fstar/dispatch.py` harvest 输入/输出基线混同 —— 旧实现重算并比较 `baseline.delivery`，使任何真实改动 allowed_paths 的 implement 回收一律 `stale_input`。现仅输入（`artifact_items`）参与 staleness，delivery 是期望输出。
2. editor 回收基线语义 —— 旧实现比较目标文件**当前**哈希与 pre-edit `baseline_sha256`，editor 完成本职写入即 `baseline_conflict`。现比较 result 报告的基线版本与 payload 基线版本；文件编辑后不同属预期。editor 的编辑意图写入不再判冲突；基于过期讨论版本的旧稿仍拒绝。
3. hooks 双回收路径 —— 旧 `fstar.runtime.hooks.worker_result` 自行构建证据（发明了 result schema 中不存在的 `validates`/`lease_token` 字段）、跳过身份/基线/范围核验并自行释放租约。现强制要求登记 payload，委托 `DispatchService.harvest` 唯一路径；无 payload 的 worker 自报：被动跳过（`dispatch_payload_required`）、显式 CLI 报 `payload_required`（exit 3）。
4. 重放双记 —— 同一 result 经宿主事件与 CLI harvest 会写两份证据。现 `meta.templates.dispatch_harvested`（任务持久、跨进程）标记已回收 dispatch_id，重放零写入（`test_replayed_result_records_nothing_twice`、`test_replay_guard_survives_new_process`、`test_hook_and_cli_harvest_do_not_double_record`、`test_worker_result_cli_harvests_with_payload`）。
5. 兄弟孤儿化 —— failed/cancelled 回收曾释放任务级协调者租约，杀死仍在途的同任务兄弟 worker。现回收只记 `dispatch_terminal` 事件、保留租约；显式释放仅 `interrupt --release-lease-token`。
6. 检查交接内存态 —— `hand_off_scope` 曾只存进程内存，新 CLI 进程的 harvest 不再识别（AC-06 实际失效）。现持久化 `meta.templates.dispatch_check_handoff`，事件 `dispatch_scope_handed_off` 留痕，跨进程生效。
7. 嵌套子任务路径匹配 —— `task_ref in parts` 子串匹配：`root` 可误配 `root-extra`，嵌套 `subtasks/child` 永不匹配。现按完整路径段前缀匹配（`test_nested_subtask_editor_scope`）。
8. 命令面越界 —— `fstar orphan` 是父 §4.1 未授权的顶层用户命令。已移除；孤儿只读报告收为 `fstar dispatch orphan` 子命令，用户入口保持 `continue`（父 implement §3 #5 孤儿只读、不自动重派，未变）。
9. 结果状态枚举缺 `cancelled` —— interrupt/检查点停止的终态无协议表达。已补（harvest 记终态、不写证据）。
10. file-mode "上游缺陷在途" 记录过期 —— core 修复早已在 79 项基线中。新增真实 file-mode 回归 `test_file_mode_artifact_map_baseline_roundtrip`（snapshot 粒度 file + harvest 往返 + 输入变更仍 stale）。
11. RD-I7 能力矩阵缺失 —— 产出 `research/dispatch-host-capabilities.md`：三级证据分级（observed-schema / fixture-test / live-delivery），本机 Claude Code 2.1.312 与 codex-cli 0.165.0 的字符串枚举为 observed-schema 级；live-delivery 0 项；含必做 e2e 清单。不宣称宿主内派发/转向已验证。
12. 零改动 done 结果证据恒 stale —— `changed_paths` 为空时曾把 payload 的**派发前** delivery（含旧 digest）原样写入证据；核心 `record`→`_validate_current` 重算 delivery 摘要必然不匹配，证据落库即 `state:"stale"`。现恒用 `delivery_snapshot(changed_paths)` 重算（空集产出自洽 digest），空改动 done 记录为 fresh 证据（`test_done_result_without_changes_records_fresh_delivery`）。

## 验收标准核对

- AC-01 通过：协议模块零宿主 import；缺字段/坏 role/绝对路径/`..`/session-only 捏造路径/editor 缺 item_ids+baseline/research 越界均拒。
- AC-02 通过：所有输出 `dispatch_mode: "adapter"`，adapter note 明示 shell CLI 不能调用当前会话原生 Agent 工具。无虚假"已启动 worker"表述。
- AC-03 通过（联合修订后语义）：身份/输入基线/范围/租约四类核验 + 重放防护，任一不匹配拒绝写入并给稳定 code。
- AC-04 通过：协调者持租约、worker 回报经核心 record 续租 +30m；session-only 全簿记静默跳过、目录集合不变。
- AC-05 通过：parallel_groups 依赖/写入/共享资源冲突分组，优先级不越依赖。
- AC-06 通过（现已跨进程成立）：持久 hand-off 标记 + 回收拒绝。
- AC-07 通过：`fstar.change.v1` 统一消息；档位决策不假设高档位。
- AC-08 通过：1 次自动重试附 prior_failure，二次失败 `dispatch_failed_persistent`→fstar-debug；环境阻塞不循环。
- AC-09 通过：orphan_report 只读、`choose_takeover_replan_or_drop`、无自动重派。
- AC-10 通过（修订语义）：editor 限定 doc 树与条目；提交按结果报告基线核对，旧稿不覆盖新结论。
- AC-11 **部分**：能力矩阵已产出，但仅 observed-schema 级；live-delivery（真实宿主内派发/转向/中断）未执行，归 e2e-verify。未写成功能保证。
- AC-12 通过：经 `register_commands`/`OPTIONAL_HANDLER_ATTR` 接入，与 core/hooks 文件不冲突；cli.py 仅模块清单一行协调。

## 实际命令与结果

- `PYTHONPATH=src python3 -m unittest tests.test_dispatch tests.test_hooks` → **Ran 113 tests ... OK**（目标套件，联合范围）
- `PYTHONPATH=src python3 -m unittest discover -s tests` → **Ran 192 tests ... OK**（Python 3.9.6，最终全量）
- `python3 -m compileall -q src/fstar tests` → 通过

## 未修复/受限项（如实报告）

- **宿主内真实派发/转向/中断/恢复未验证**（live-delivery 0 项）。e2e 清单在 research/dispatch-host-capabilities.md。
- Codex postToolUse payload 文件路径键 schema 未暴露，doc 路径提取 to-verify；回退路径已实现。
- 工具绑定（tool-binding）并行实现中，其 `tests/test_tools.py` 属他人所有权，任何失败不归本检查。
- 静态语义内容/源模板缺口是 workflow-content 的开放项，不由本 runtime 单测关闭。
