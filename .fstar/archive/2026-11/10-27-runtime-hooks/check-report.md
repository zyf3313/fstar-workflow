# runtime-hooks 联合独立检查报告

日期：2026-10-29。检查者：trellis-check（联合 runtime-dispatch + runtime-hooks 范围）。
解释器：**Python 3.9.6**。无 Git 仓库，检查按直读源码执行。

## 修复的缺陷（全部有回归测试）

1. **worker-result 双回收路径（联合核心缺陷）** —— 旧实现绕过 dispatch 校验自行 `EvidenceService.record`，且发明了 dispatch result schema 中不存在的 `validates`/`lease_token`/`worker_id` 字段，用户 payload 可以自选 worker 身份并把任意内容写进证据。现强制要求登记的 dispatch payload 并委托 `fstar.dispatch.DispatchService.harvest` 单一路径：派发身份、输入基线、范围、重放防护（任务持久 `meta.templates.dispatch_harvested`）、租约与独立性闸门全部由该路径拥有。宿主事件 + CLI harvest 不会双记（`test_hook_and_cli_harvest_do_not_double_record`）。无 payload 的 worker 自报：被动跳过 `dispatch_payload_required`；显式 CLI 报 `payload_required`（exit 3，不静默伪装成功，`test_worker_result_cli_requires_dispatch_payload`）。CLI 增加 `--payload` 参数承载登记 payload。
2. **失败/取消释放任务租约孤儿化兄弟 worker** —— 旧实现 done/failed/cancelled 均直接 `release_lease`。同任务并行派发的兄弟 worker 会被杀死。现回收路径只记 `dispatch_terminal` 事件、保留协调者租约；`outcome["lease_released"]` 恒 False，显式释放归 `interrupt --release-lease-token`。
3. **doc-change 变更消息形状** —— 旧输出 ad-hoc 字段（`"source": "doc-change hook"`、`file`、字符串 action），与 runtime-dispatch 的 `fstar.change.v1` 不一致且丢失受影响条目数据。现输出 canonical `fstar.change.v1`：source=file、origin=文件路径、affected 含按 artifact_map 的真实 plan_item_ids/artifact_items、old/new fingerprints、action=pause_and_redispatch、affected_evidence；映射未建立时 `unknown_plan_items: true` 显式保守回退，不输出空 affected（`test_doc_change_message_is_canonical_change_schema`、`test_doc_change_unknown_plan_items_conservative`）。
4. **worker-context 不加载适用规范正文** —— 旧实现只注入 routing/角色卡/任务 doc，违反父 §4.4「完整适用规范正文」。现按 implement/check 两个 manifest（`implement.jsonl`/`check.jsonl`）加载全部存在且安全的条目正文（`inject.manifest_entries` + `spec_body_inputs`），拒绝绝对路径/`..`，缺失文件不静默出现为幻影输入；每条带 sha256/version 指纹（`test_spec_bodies_from_manifests_injected`）。预算超限时 required 输入必入 unloaded 清单并带 MANDATORY re-read 指令，从不静默丢弃（`test_overloaded_required_context_never_silently_dropped`）。
5. **跨产品角色误映射** —— `_role_from_payload` 曾把 `trellis-*` 剥前缀后映射为 fstar 角色，fstar 注入会进入 Trellis 子代理。现只认 fstar 前缀与裸角色名（`test_no_trellis_role_mapping`）。

（另：dispatch 侧缺陷 12 —— 零改动 done 结果证据恒 stale —— 经由 worker-result 委托的同一 harvest 路径修复，见 dispatch 侧报告。）

## 验收标准核对

- 4 hooks 边界：无 turn-context、无第 5 hook、无自定义入口（`test_exactly_four_semantic_hooks_both_hosts`、`test_no_turn_context_hook`）。
- session-context：未 init 静默且 routing 仍注入、不建 `.fstar` 元数据；已 init 注入当前任务摘要且 task.json 字节不变（读只读）；会话隔离；仅轻检查（tools.yaml 存在性/detected_at），无完整扫描、无写。
- worker-context：四角色差异注入、每输入指纹、超限 unloaded+补读要求、无 task.json 静默、session-only 引用、plan 项条目快照经核心 snapshot。
- worker-result：done 经单一路径写 delivery 且续租；failed/cancelled 不释放租约记终态事件；不写 acceptance；旧 token/范围越界/任务不匹配拒绝。
- doc-change：幂等（重复触发零写入）、无关文件静默、planning 无证据零噪声、已有证据无 phase 豁免、非 doc 路径跳过、active_lease 被动跳过、显式缺文件报错。
- CLI 注册：`fstar hook` 族 + `hook plan --host`；未 init 显式任务请求报错（`project_not_initialized`/`task_not_found`，不静默成功）；内部 ImportError 穿透、模块缺失静默跳过（两测分开）。
- 宿主事件映射：verified 标志仅反映二进制/schema 观察（observed-schema 级），to_verify 项与回退齐全；`python3 -m fstar.runtime <hook>` stdin payload 语义已测（未 init 目录 exit 0 无噪声；worker-context 非本产品角色静默；worker-result 宿主事件路径零输出——结果消息不可能由事件携带）。
- 注册形态只读：`hook plan` 两宿主输出含 dedup key 与精确撤销字段，不写宿主设置。

## 实际命令与结果

- `PYTHONPATH=src python3 -m unittest tests.test_dispatch tests.test_hooks` → **Ran 113 tests ... OK**（联合目标套件）
- `PYTHONPATH=src python3 -m unittest discover -s tests` → **Ran 192 tests ... OK**（Python 3.9.6，最终全量；含并行中的 tool-binding 套件）
- `python3 -m compileall -q src/fstar tests` → 通过

## 未修复/受限项（如实报告）

- **宿主事件 live-delivery 未验证**：SessionStart/PreToolUse/PostToolUse/SubagentStart/SubagentStop 字符串在 Claude Code 2.1.312 二进制与 codex-cli 0.165.0 schema 中确认存在（observed-schema 级），fstar 条目从未真实注册投递。必做 e2e 清单在 `../10-27-runtime-dispatch/research/dispatch-host-capabilities.md`。
- Codex postToolUse 的文件路径键未由 schema 暴露（`verified: false`）；doc-change 在 codex 上的提取按回退路径工作，待真实运行核对。
- SubagentStop 不能携带结果消息：worker-result 的主调用方是回收边界（已实现并测）。
- 与 runtime-dispatch 的共享 schema 修订已同步进本子设计 §4.3/§6。
