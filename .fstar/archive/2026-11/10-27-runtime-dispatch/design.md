# 派发协议技术设计

## 1. 权威与边界

父 `../10-25-fstar-workflow-design/{prd,design,implement}.md` 为当前权威，重点 design §3.7、§3.2–3.4、§4.1、§4.4。父 design 注入被截断时必须 Read 补齐全文。研究稿 `worker-adapter-protocol.md` 是两宿主传输观察，供实测起点，不构成功能保证；其文末的 check 用例审批契约（test-cases approved 前置）已被父 PRD/design 撤销，本设计不恢复。子 PRD AC 为验收依据。

本轮只准备规划文件。实现 Python 3.9 标准库、`from __future__ import annotations`、Optional/Sequence，无第三方依赖。独占 `src/fstar/dispatch.py`、`tests/test_dispatch.py` 与本目录 `research/dispatch-host-capabilities.md`（实测记录）；不改 core/hooks/content 的文件。核心源码（`src/fstar/tasks.py`、`src/fstar/evidence.py`、`src/fstar/cli.py`）不进 jsonl 注入清单，由执行者开工时按范围自行 Read 并核对实际签名。**模块选择**：新增 `src/fstar/dispatch.py` 独占派发协议（不并入 hooks 或 tasks），cli.py 经既有 `_register_optional(subparsers, "runtime")`/`"dispatch"` 机制自动发现（cli.py 的模块清单当前为 `("project","runtime","tools")`，实施时与 hooks 协调：该行是两任务的共享协调点，需单一写者加入 `"dispatch"`——见 §7 待协调项）。

## 2. 模块分层

```
dispatch.py
  协议层（纯数据/校验，无 IO）     build/validate payload、result、change message、parallel groups
  登记层（薄，可注入 TaskService） 持久任务租约/登记、最小闭环静默跳过
  回收层（核验+写证据）            verify identity/baseline/scope/lease → EvidenceService.record
  CLI 适配层                       register_commands → dispatch/interrupt/doc-edit
宿主适配器（宿主内，主 Agent 侧）  消费 CLI 产出的 payload，经宿主原生 Agent 工具实际派发与回收
```

协议层不 import 宿主特定代码，保证换传输不改协议（AC-01）。宿主适配器本体是主 Agent 会话内的行为指引 + 少量可在 dispatch.py 提供 payload→提示词的纯函数；无法在 Python 单测中证明宿主行为，单测只覆盖协议/登记/回收，宿主部分进实测记录。

## 3. 派发协议数据契约

### 3.1 payload（`fstar.dispatch.v1`）

```json
{
  "schema": "fstar.dispatch.v1",
  "dispatch_id": "<uuid>",
  "task_ref": "<task id|relative path|'session-only'>",
  "role": "implement|check|research|editor",
  "plan_item_ids": ["..."],
  "baseline": {
    "artifact_items": [{"artifact": "doc/prd.md", "items": [{"id": "R-001", "sha256": "..."}]}],
    "delivery": {"paths": [{"path": "src/x.py", "sha256": "..."}], "digest": "..."}
  },
  "input_versions": [{"path": "doc/prd.md", "sha256": "...", "version_ref": "..."}],
  "allowed_paths": ["src/fstar/dispatch.py"],
  "read_context": [{"path": "...", "sha256": "..."}],
  "required_validations": ["unittest tests.test_dispatch"],
  "return_conditions": {"done": "...", "blocked": "...", "failed": "..."},
  "prompt_first_line": "Active task: <path>|Active task: session-only"
}
```

构建：`build_payload(role=..., task_ref=..., plan_item_ids=..., allowed_paths=..., read_context=..., ...)`；持久任务时 `baseline.artifact_items` 直接复用 `EvidenceService.snapshot(ref, artifact, items)`（条目级指纹，由核心计算，本模块不另造哈希），`baseline.delivery` 复用 `EvidenceService.delivery_snapshot(paths)`。最小闭环时由调用方提供文件快照（同一 digest 规则）。`validate_payload(payload)` 检查：schema/必需字段、role 枚举、路径安全（拒绝绝对路径/`..`，复用与核心一致的边界规则——实现为本地 `_safe_relative` 或从 store 导入只读工具，不绕过项目根）、`prompt_first_line` 与 task_ref 一致性（session-only 不捏造路径）。

editor 专属：`item_ids[]`（限定条目）+ `baseline_sha256`（目标文件当前哈希）；`validate_payload` 对 editor 要求两者存在且 `allowed_paths` 全部位于任务 doc 树（持久任务）或授权产物根（session-only）。research 专属：`allowed_paths` 须位于 research 范围。

### 3.2 result（`fstar.dispatch.result.v1`）

`dispatch_id/role/status(done|blocked|failed)/changed_paths/artifact_refs/validation_facts{command,result,exit_code,duration,retries}/blockers/input_baseline/delivery_baseline`。`validate_result` 检查结构；`verify_result(result, payload, task)` 执行回收核验（§5）。

### 3.3 change message（`fstar.change.v1`）

`change_id/来源(conversation|file)/origin(用户原话或文件路径)/affected{plan_item_ids,artifact_items}/old_fingerprints/new_fingerprints/action(propagate|pause_and_redispatch)`。`build_change(...)` 纯构造；传导决策按宿主能力档位（§6）。

## 4. 登记层与租约

`DispatchService(store, *, clock)` 持有可注入 `TaskService/EvidenceService`（复用核心服务，不重写事务）。

- **register(payload)**：task_ref 为 session-only 时返回 `{registered: false, persistence: "session_only", payload: ...}`，不写任何文件（最小闭环不落盘）。持久任务时：任务须 in_progress 且无活跃他人租约；协调者经 `TaskService.acquire_lease(ref, holder=coordinator_id, role="coordinator")` 取租约（已有活跃租约且 holder 相同则复用 token）。登记事件使用统一封套 `{id,at,source,type:"dispatch_registered",data:{dispatch_id,role,plan_item_ids}}`——注意核心 `validate_task` 的事件封套允许任意 type 字符串，`dispatch_registered` 合法；里程碑集合不含它，随 events 软 200 压缩，派发记录的持久信息以证据/租约为准。
- 派发登记不改变 phase；实施/检查/修复都在 in_progress。
- worker 不持任务租约、不写 task.json；回报由协调者处理（父 design §3.3）。

## 5. 回收层（verify → 核心写证据）——联合 check 修订版

`harvest(result, payload, *, lease_token)` 是**唯一**回收路径（hooks worker-result 委托此处，不允许旁路）。顺序核验，任一步失败抛 DomainError 并给出 code/details，不写部分结果：

1. **身份**：result.dispatch_id == payload.dispatch_id，role 匹配；result 结构完整。
2. **输入基线**：仅重算 payload.baseline 的**输入**（`artifact_items`）指纹；`baseline.delivery` 是 worker 的期望**输出**，不参与 staleness 比较——合法交付写入（implement 改动其 allowed_paths）不得被误判 stale。输入已变 → `stale_input` + change message，协调者显式重派。
3. **范围**：`set(result.changed_paths) ⊆ set(payload.allowed_paths)`；越界 → `scope_violation`。持久检查交接标记存 `meta.templates.dispatch_check_handoff`（任务持久，跨进程生效），handed-off 范围的 implement 回收拒绝。editor 冲突语义：比较 result 报告的 `baseline_sha256`（编辑所基于的讨论版本）与 payload 的 `baseline_sha256`；不一致 → `baseline_conflict`（旧稿不覆盖新结论）。编辑目标文件在编辑后与 pre-edit 基线不同是**预期行为**，不是冲突。
4. **重放**：已回收的 dispatch_id 存 `meta.templates.dispatch_harvested`（任务持久）；同一 result 二次回收返回 `replayed` 且零写入——宿主事件 + CLI harvest 不会双记。失败/取消 → 记 `dispatch_terminal` 事件，**不释放协调者租约**（同任务兄弟 worker 不得被孤儿化；显式释放走 `interrupt --release-lease-token`）。
5. **租约/证据**：经 `EvidenceService.record(ref, evidence=..., lease_token=token)` 写入——核心在锁内校验 token、未过期、自动续租 +30m、check 独立性闸门；delivery 证据按 result 的 changed_paths 由 delivery_snapshot 构建（kind=delivery）。
6. 回收后按 role 路由：implement delivery → 协调者决定 check 派发；check 通过证据进入核心 acceptance_status 观察面。worker done 只表示回收完成，不等于验收（核心闸门已保证）。

`interrupt(dispatch_id, reason, mode)`：登记停止意图与基线，产出传导决策（§6 档位），不改任务 phase；持久任务下可选释放/保留租约由调用方显式选择。

**命令面注意**：孤儿恢复的用户入口是父命令面的 `continue`；`fstar dispatch orphan` 只是回收层的只读报告子命令，不是新增顶层用户命令。

## 6. 变更传导与宿主能力档位

宿主能力以**实测**为准，记录于 `research/dispatch-host-capabilities.md`（实施时产出），能力分三档，协议按档位决定动作，不假设高档位可用：

| 档位 | 触发 | 动作 |
|---|---|---|
| realtime-steer | 宿主支持向运行中 worker 送达消息并确认 | 构造 change message → 适配器 steer → 收到 worker 确认对齐后继续 |
| checkpoint-stop | 不支持实时转向 | 对受影响范围 interrupt → worker 在检查点停止 → 回收时按新基线重派（新 dispatch_id） |
| process-stop | 也不支持优雅停止 | 适配器中断/杀 worker → 遗留产物按孤儿处理（只读核实） |

起点观察（待实测，不作保证）：Codex app-server 协议含 `turn/steer`/`turn/interrupt`/`thread/queue/add`，要求双向 RPC 握手与反向请求应答；Claude Code 子代理派发的实时转向能力未核实。文件变更源（doc-change hook / 核心重算）产出同一 change message 格式，两类触发源统一。

失败重试：`retry_policy = {max_auto_retries: 1}`；适配器/宿主层失败自动重派 1 次且新 payload 附 `prior_failure{reason, dispatch_id}`；仍失败 → 返回 `dispatch_failed_persistent`，路由进入 fstar-debug（routing 已定义）。环境阻塞（如权限拒绝）不重试，直接 blocked 结果。

## 7. 并行分组与检查交接

`parallel_groups(plan_items)`：输入为 plan 项（id、depends_on、allowed_paths、shared_resources）；输出分组列表——同组内项依赖闭合且 allowed_paths/shared_resources 两两无交集；有交集或跨组依赖的项归入更晚的组。纯函数可确定性测试。优先级只影响组内排序，不越过依赖（不实现调度器）。

check 交接：协调者将范围 S 交 check 时，对 S 内 plan 项的未完结 implement 派发标记 `write_handed_off: true`；此后 S 范围的 implement result 回收按范围核验拒绝（scope_violation 语义复用）；S 外无冲突项继续。检查自修后的生产/测试改动由 check result 的 changed_paths 表达并进入新 delivery 基线。

## 8. CLI 命令（经 register_commands）

`register_commands(subparsers)` 注册并 `set_defaults(_fstar_module_handler=...)`（cli.py `OPTIONAL_HANDLER_ATTR` 约定；注意 cli 当前从 `_fstar_project_handler` 桥接 project 模块，本模块直接用规范键）：

| 命令 | 输入 | 输出 |
|---|---|---|
| `dispatch implement\|check\|research\|editor` | `--payload FILE` 或结构化参数、`--session`、`--project` | 校验后的 payload + 登记/租约结果 + `dispatch_mode: "adapter"` 与宿主适配调用说明；绝不声称已启动 worker |
| `dispatch harvest` | `--result FILE`、`--payload FILE` | 核验结论 + 核心证据写入结果或明确拒绝原因 |
| `interrupt [task]` | `--dispatch-id`、`--reason`、`--mode` | 停止意图登记 + 传导档位决策 |
| `doc-edit [task]` | `--file`、`--items`、`--baseline`、`--payload` | editor 协议入口：构建/校验 editor payload（非直接改写文件） |

失败走 DomainError 的稳定 code/message/details 与退出码约定（0/1/2/3/4 沿核心）。所有命令支持 `--json`。CLI 只在 shell 侧做可完成的部分；实际派发、实时转向、worker 交互属于宿主内适配器，文档与 `--json` 输出如实区分。

## 9. 测试与验证

`tests/test_dispatch.py`（unittest、临时目录、真实 TaskService/EvidenceService 子系统）：

- payload/result/change 结构校验正负例（缺字段、坏 role、绝对路径、session-only 捏造路径、editor 缺 item_ids/baseline）。
- register：持久任务取租约/事件登记；session-only 不落任何文件（前后目录集合对比）。
- harvest：身份/基线/范围/租约四类拒绝各有明确 code；合法 implement result 经核心 record 写入 delivery 证据且续租；check result 走核心 `_validate_check` 全链（五态、独立性）；输入已变返回 stale_input + change message 而非写入过期结果。
- parallel_groups：依赖链、路径交集、共享资源分组确定性；优先级不越依赖。
- retry：失败重试 1 次、附 prior_failure、二次失败进 debug 路由返回值；环境阻塞不重试。
- 孤儿：租约过期的 continue 状态为只读 next=choose_takeover_replan_or_drop（复用核心行为，不自行重派）。
- check 交接：handed-off 范围 implement 回收被拒。
- CLI：dispatch/dispatch harvest/interrupt/doc-edit 经 build_parser 实际可调用，session-only 模式无 `.fstar` 元数据。

宿主适配器：payload→worker 提示词构造为纯函数并测试首行/字段注入；真实宿主派发/转向/恢复以两宿主实测记录（`research/dispatch-host-capabilities.md`）+ e2e-verify 覆盖，不伪造单测通过。

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 宿主实际不支持假设的派发/转向 | 能力档位降级设计；实测记录（research/dispatch-host-capabilities.md，分级证据）；缺口如实报告，不虚构 |
| cli.py 模块清单未含 "dispatch" | 已加入；与 hooks 的 `fstar.runtime` 互斥 |
| 回收时输入已变 | stale_input 显式拒绝 + change message；核心 record 双保险 |
| 角色文本被当成安全边界 | 输出/文档明确 protocol-not-sandbox；范围核验是事后检查 |
| 输入基线 vs 期望输出混淆 | 仅输入指纹参与 staleness；delivery 是期望输出（联合 check 修复） |
| 结果重放/宿主事件与 CLI 双回收 | 任务持久 dispatch_harvested 标记；replayed 零写入 |
| 失败释放租约孤儿化兄弟 worker | 回收只记终态事件不释放租约；显式释放走 interrupt |
