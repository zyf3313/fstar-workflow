# Runtime Hooks 技术设计

## 1. 范围与边界

- 4 个语义 hook：session-context / worker-context / worker-result / doc-change。**无 turn-context、无第 5 个 hook、不开放自定义 hooks。**
- hook 是被动簿记与注入层：定位、注入、幂等指纹/stale/事件；所有状态/证据/租约事务经核心 API，不复制核心逻辑。
- 外部编辑绕过 hook 由核心边界重算补足（派发/回收/读取/恢复/验收/归档重算指纹），hook 不承担新鲜度兜底责任。

## 2. 模块布局（Python 3.9 stdlib）

```text
src/fstar/runtime/
  __init__.py        # 空或版本常量；包名 fstar.runtime 为 runtime-hooks 独占
  hooks.py           # 4 个语义 hook 的入口函数 + 宿主事件映射表
  inject.py          # 注入组装：预算、指纹、全量适用规范加载
  registration.py    # 宿主注册形态（只读 plan 输出；写入归 package-install）
```

- CLI 注册走 `register_commands(subparsers)` + `parser.set_defaults(_fstar_module_handler=handler)`（cli.py 已在服务发现前分派，兼容未 init 目录）。命令族：`fstar hook session-context|worker-context|worker-result|doc-change`、`fstar hook plan --host claude|codex`。
- **内部 ImportError 不吞**：`cli._register_optional` 对模块缺失（find_spec 为 None）静默跳过是既有行为；但 `fstar.runtime` 内部 import 核心失败必须让异常穿透，不 except-pass。
- 不依赖 core file-mode（`mode:"file"`）artifact_map 往返（core 修复在途）；实现与测试只使用条目级映射路径。

## 3. 语义 hook ↔ 宿主事件映射

**事件名与 payload 为 to-verify**：实现期在真实宿主实测并记录（版本、事件名、输入 JSON 样例）；下表是当前假设，不得写成保证。

| 语义 hook | Claude Code 假设事件（to-verify） | Codex 假设事件（to-verify） | 缺事件回退 |
|---|---|---|---|
| session-context | SessionStart（startup/clear/compact 等价 source） | Codex 会话启动等价事件；若无，入口 skill/命令主动调用 | `fstar hook session-context` 手动/入口调用，注入同一输出 |
| worker-context | PreToolUse（Task/Agent 工具派发前） | Codex 派发前等价；若无，派发包装入口调用 | runtime-dispatch 派发包装器调用同一入口 |
| worker-result | SubagentStop / Task 完成回收 | Codex turn/completed 等价 | runtime-dispatch 回收边界调用同一入口 |
| doc-change | PostToolUse（Edit/Write 命中任务 doc/*.md） | Codex 文件写等价；若无，命令边界调用 | `fstar evidence invalidate` + 读取边界重算（核心已覆盖） |

宿主缺事件时用派发/回收/命令边界执行同一逻辑并报告覆盖限制，不加第 5 个 hook。映射表数据驱动（dict），宿主适配差异不散落逻辑。

## 4. 各 hook 行为

### 4.1 session-context（会话启动）

输入：宿主 payload（session_id、cwd、source）。步骤：
1. `find_project_root` 定位项目；未 init → 只注入 routing 全文 + 用户级索引（存在时），任务部分整体跳过，无噪声。
2. 已 init：`load_config` 读预算与语言；读项目/用户索引；`store.current(session_id)` 读当前任务（只读，不写 pointer）。
3. 轻检查：tools.yaml 存在性 + detected_at 过期提示（`shutil.which` 级，无完整扫描）。
4. 输出（stdout，宿主注入）：routing 全文、索引、当前任务摘要（phase/blocked/lease/awaiting_acceptance 派生标记，来自 `TaskService.state` 只读）、learn 候选提示（仅指向现有节点，不建台账）。
5. 不做：归档巡检、每轮注入、完整工具扫描、任何写操作。

### 4.2 worker-context（派发前，硬绑定角色）

输入：role（implement/check/research/editor）、task_ref、plan_item_ids、baseline。步骤：
1. 组装注入：角色卡全文、任务 doc/prd、design（如有，带条目快照与指纹）、plan 相关项、全部适用规范正文（按项目索引主题 Applies to/read_when 过滤后**完整加载正文**）、共享契约。每个输入附 `{path, sha256, version}`。
2. 预算：`context_injection.max_file_bytes/max_artifact_bytes/max_total_bytes`（config 键沿用父 §4.2；缺省用保守默认）。超限：输出索引行 + `unloaded` 清单；**执行者必须补读适用正文才执行**——注入文本明示该要求，不静默截断。
3. 无 task.json / 未 init：注入 routing + 角色卡 + 会话目标引用（`Active task: session-only`），跳过任务簿记。
4. 指纹用 `EvidenceService.snapshot`（条目级 artifact_map）与 `file_digest`；不自行实现哈希。

### 4.3 worker-result（回收）

输入：dispatch 结果（status ∈ done/failed/cancelled、changed_paths、产物引用、基线）**与登记的 dispatch payload**（宿主事件无法携带 payload；回收边界/CLI `--payload` 供给）。步骤：
1. 核对 dispatch 身份与 payload↔task 一致性（复用 runtime-dispatch 校验）。
2. 委托 `fstar.dispatch.DispatchService.harvest` 单一路径：done → 核心 `EvidenceService.record`（核心内部校验 lease token、续租 +30m、check 独立性、重放防护）；failed/cancelled → 终态事件，**不释放协调者租约**（兄弟 worker 可能仍在途；显式释放走 `interrupt --release-lease-token`）。无登记 payload 时：被动静默跳过（`dispatch_payload_required`），显式 CLI 报 `payload_required`——worker 自报不构成回收依据。
3. 路由提示：done→check 派发建议；failed→debug（最多 1 次重试归 runtime-dispatch）；cancelled→变更传导检查点。
4. **不写 acceptance**；输出仅登记事实与下一步建议。

### 4.4 doc-change（doc/*.md 编辑后，幂等）

输入：变更文件路径（项目相对）。步骤：
1. 命中当前任务 `doc/*.md` 才处理；其余文件静默跳过（无输出）。
2. 幂等：重算条目指纹（`EvidenceService.snapshot`），与既有证据比对；无变化 → 不写任何内容。
3. 有变化：`EvidenceService.invalidate(file=...)`（核心事务内 stale 相关证据 + 事件 + completed 回退 in_progress 语义）；输出一行变更传导提示（受影响条目/计划项 + 新指纹）。
4. planning 中无既有证据 → 无 stale、无噪声；**已有证据不因 phase 豁免**。
5. 不跑测试、不写报告、不递归处理派生文件。

## 5. 静默跳过 vs 显式报错

| 场景 | 行为 |
|---|---|
| hook 被动簿记，无 task.json / 未 init | 静默跳过任务部分，exit 0，无输出噪声；routing/角色注入照常 |
| 显式任务 CLI（start/accept/state…）缺项目/任务 | 核心既有 DomainError 清楚报错（不改动） |
| hook 输入缺 task_ref 但任务簿记需要 | 静默跳过该部分，不伪造 |
| `fstar hook` 显式子命令在未 init 目录请求任务数据 | 报 `project_not_initialized`，不静默成功 |

## 6. 与 runtime-dispatch 的协调契约

- **结果消息**：worker-result 消费 dispatch 结果 `{dispatch_id, role, status, changed_paths, artifacts, validation_facts, duration, retries, blockers, input_baseline, delivery_baseline}`；schema 由 runtime-dispatch 拥有，本子任务只读消费，字段变更经 runtime-dispatch。
- **回收单一路径（联合 check 定案，2026-10-29）**：worker-result 不再自行构建/记录证据，也不自行释放租约。它强制要求登记的 dispatch payload（worker 自报的 role/baseline/identity 不足以通过核验），核验 payload 与任务一致后委托 `fstar.dispatch.DispatchService.harvest`——派发身份、输入基线、范围、重放防护（任务持久 `meta.templates.dispatch_harvested`）与证据记录全部由该路径拥有。宿主事件与 CLI harvest 不可能双重记录。失败/取消的租约处置也归该路径：只记终态事件，不释放协调者租约（兄弟 worker 可能仍在途）。
- **变更消息**：doc-change 产出 canonical `fstar.change.v1`（schema 由 runtime-dispatch 拥有）：`change_id/source(file)/origin(文件路径)/affected{plan_item_ids,artifact_items}/old/new_fingerprints/action`。受影响条目按既有 artifact_map 保留真实数据；映射未建立时 `affected` 显式 `unknown_plan_items: true` 保守回退，不得输出空 affected 假装无影响。送达机制（实时转向 vs 检查点停止）归 runtime-dispatch。
- **模块命名**：`fstar.runtime`（hooks）独占；dispatch 适配器使用其他模块名（如 `fstar.dispatch`），互不写入对方文件。
- worker-context 入口被 dispatch 派发包装器复用（宿主无 PreToolUse 等价事件时的回退路径）。worker-context 按 implement/check 两个 manifest 完整加载适用规范正文（`inject.manifest_entries` + `spec_body_inputs`），不静默省略。

## 7. 注册形态（只读）

`fstar hook plan --host claude|codex` 输出该宿主的注册条目结构（事件名、命令行、matcher），供 package-install 实际写入与 doctor 核对：
- Claude Code：settings.json `hooks` 数组追加项（去重键 = event + command）。
- Codex：按实测支持的位置（to-verify）。
- 只输出形态，不写宿主设置；卸载/撤销归 package-install。

## 8. 所有权与依赖边界

| 项 | 所有权 |
|---|---|
| 状态/证据/租约/事件事务 | core-commands（本子任务只调用） |
| config/索引/init | project-layout（只读消费） |
| skills/roles/routing 文本 | workflow-content（只读注入） |
| 派发/重试/转向/孤儿恢复 | runtime-dispatch（本子任务提供 context/result 入口） |
| 宿主设置实际写入/doctor | package-install（本子任务提供 plan 形态） |
| file-mode artifact_map 往返 | core-commands 修复在途；**本子任务不依赖、不阻塞** |

## 9. 未决技术依赖（如实报告，不虚构）

1. 两宿主实际事件名与 payload —— 实现期实测（to-verify），无网络时以本机宿主二进制实测为准。
2. Codex 会话/文件事件等价性 —— 若无等价，按 §3 回退并记录覆盖限制。
3. `context_injection` 预算键当前 config.py 未定义 —— 本子任务以默认值实现读取（缺键回退默认），键的正式入册随 project-layout/config 演进，不私改 config schema。
4. 注入体积与宿主实际上限的关系 —— 注入预算控制 fstar 侧输出；宿主自身限制由 doctor（package-install）报告。
