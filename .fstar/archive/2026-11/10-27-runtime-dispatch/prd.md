# 派发协议与原生适配

## 目标与当前授权

实现 fstar 自研派发协议与宿主原生派发适配（implement / check / research / editor 四角色），含结果回收、依赖安全的并行协调、写入交接、统一变更传导、限次重试与孤儿只读恢复。父任务 `../10-25-fstar-workflow-design/{prd,design,implement}.md` 为当前权威；用户已授权第一版全部十个子任务，本轮仅刷新本目录规划文件，不启动任务、不写产品代码、不做 git、不重复审批。

传输采用宿主原生 Agent 工具：Claude Code 为宿主 Agent/Task 工具的子代理派发，Codex 按其实际支持的等价机制（app-server thread 或宿主内子代理），实际能力在实施时实测并在文档记录，不把推测写成保证。协议归 fstar，与传输解耦：换宿主不改协议字段。

## 前置依赖

依赖 `core-commands`（`fstar dispatch` 登记的结果要经核心 EvidenceService/TaskService 写回任务状态与证据）与 `workflow-content`（角色卡与 skill 是被派发对象载体，12 skills/4 roles/11 模板已交付）。`runtime-hooks` 为同级并行子任务：hooks 管宿主事件簿记（worker-context 注入、worker-result 回收辅助、doc-change 提示），本任务管协议与派发本身；两者通过本设计的共享 payload 契约对接，文件不冲突（hooks 建议独占 `src/fstar/hooks.py`，本任务独占 `src/fstar/dispatch.py`，均在 cli.py 经 `register_commands(subparsers)` + `_fstar_module_handler` 注册）。依赖关系写在这里，不靠父任务目录顺序隐含。

## 需求

### RD-01 派发协议（协议归 fstar，传输解耦）

派发 payload 统一字段，由 CLI `dispatch` 准备与校验、由宿主适配器消费：

`dispatch_id`（UUID）、`task_ref`（持久任务为任务 id/路径；最小闭环为 `session-only`）、`role`（implement|check|research|editor）、`plan_item_ids[]`、`baseline`（输入快照：需求/计划条目指纹 + 交付文件快照）、`input_versions`（每个输入文档的版本/SHA-256 指纹）、`allowed_paths[]`（项目相对路径）、`read_context`（须完整读取的文档路径与指纹清单）、`required_validations`（必须实际执行的验证）、`return_conditions`（完成/阻塞/失败判定）、`prompt_first_line`（持久任务 `Active task: <路径>`，无任务 `Active task: session-only`）。

worker 返回统一字段：`dispatch_id`、`role`、`status`、`changed_paths[]`、产物引用、验证事实（真实命令/结果/耗时/重跑数）、阻塞信息、输入基线与交付基线。CLI 只做结构校验与登记，不生成结论。

### RD-02 CLI dispatch：准备/校验/登记，不做实际派发

`fstar dispatch implement|check|research|editor --payload FILE`（或结构化参数）产出：完整校验后的派发 payload + 持久任务下的租约/登记簿记 + 供宿主适配器消费的调用说明。**CLI 在 shell 中不能调用当前会话的原生 Agent 工具**——实际派发由宿主内适配器（主 Agent 经宿主 Agent 工具执行）完成。CLI 输出必须明确 `dispatch_mode: adapter`，不得暗示 shell 命令已启动 worker。持久任务时按 §RD-03 登记租约；最小闭环（无 task.json）时校验 payload、跳过登记、不落任何 fstar 元数据。

### RD-03 角色与租约纪律

- 持久任务：主 Agent（协调者）持有任务租约（`TaskService.acquire_lease`，holder 记 coordinator），worker 不写 task.json/plan；worker 回报由协调者经 `EvidenceService.record(ref, evidence, lease_token)` 写证据（record 在有效回报时自动续租 +30m）。
- check 证据须满足核心校验：producer.role=check、scope=incremental|final、五态结果、真实 run_id/environment/delivery、producer 与 delivery producer 不同（核心已强制独立检查闸门）。
- check 交接：某范围交 check 后，implement 停止该范围写入；无写入/共享资源冲突的其他项可继续。
- editor 派发额外限定：`allowed_paths` 仅指定 doc 文件、`item_ids` 限定指定条目、`baseline_sha256` 绑定讨论版本；提交前核对基线哈希，不匹配返回主 Agent 合并/重派，旧稿不得覆盖新结论。
- research 派发限定 research 路径，不改生产代码/任务状态。

### RD-04 依赖安全的并行分组

从 plan 的任务依赖与写入范围推导并行组：依赖满足且 `allowed_paths`/共享资源无交集的 implement 项可并行派发；有共享文件/接口/配置冲突的项串行。优先级不越过依赖。worktree 隔离不能自动消除逻辑依赖。协调者单写 plan 进度。

### RD-05 统一变更传导

对话变更（用户中途补充）与文件变更（doc/*.md 等输入被改）统一为变更消息：`change_id`、来源、受影响条目/计划项、旧/新指纹、动作。宿主支持实时转向（steer/interrupt 后送达，Codex 协议有 `turn/steer`，Claude Code 视实际支持）时传达并确认；不支持时对受影响范围做检查点停止，回收时按新基线重派；旧结果只留历史不算当前通过。传导不依赖“实时传话必定成功”。

### RD-06 失败重试与 debug

派发失败（适配器/宿主层失败）自动重试最多 **1 次**，重试 payload 附上次失败原因；仍失败停止派发并进入 debug 路由（routing 已定义 fstar-debug 核心自动）。环境阻塞不循环重试。无进展修复也进 debug。

### RD-07 孤儿恢复（只读，不自动重派）

跨会话 continue 发现孤儿租约（租约过期且无有效回报）时只读展示：状态、遗留产物、真实 worker 情况；由用户决定接管/重派/放弃（核心 `continue --action takeover` 等已有）。恢复不假称原 worker 仍存活或上下文已恢复。核心命令边界（读取/回收/验收）重算关键指纹兜底外部编辑。

### RD-08 多 Agent 包未启用时的降级

未启用 multi-agent 扩展包时不走四角色派发；但 implement/check 分离的底线不降级：主 Agent 切换角色执行，不得在同一动作里既写实现又宣布检查通过。（`fstar dispatch` 命令本身仍可准备协议数据，路由层决定是否派发。）

### RD-09 宿主能力实测与如实记录

Claude Code / Codex 的实际派发机制、实时转向、中断、恢复、成本报告在实施时以真实宿主版本实测；`research/worker-adapter-protocol.md` 的观察（Codex 双向 RPC/握手/反向请求、Claude stream-json）作为起点，不作为保证。不支持的 capability 明确列为降级路径，不虚构等价。worker 权限遵循用户已选无交互执行模式及宿主实际权限，角色卡/派发字段是协议约束不是安全沙箱（父 design §3.4/§3.7）。

## 交付物

- `src/fstar/dispatch.py`：协议定义/校验、payload 构建、结果回收核验、并行分组推导、变更消息、CLI 子命令注册（dispatch/interrupt/doc-edit）。
- 宿主适配指引与实测记录（两宿主各自的实际派发方式、转向/中断/恢复支持矩阵）。
- `tests/test_dispatch.py`：协议校验、回收核验、并行分组、重试、孤儿只读、editor 基线冲突、最小闭环不落盘的确定性测试（host adapter 部分以接口桩+人工实测记录覆盖，不伪造宿主行为为单测通过）。

## 验收标准

- [ ] AC-01：协议 payload/返回字段完整校验；缺 dispatch_id/role/baseline/allowed_paths 等必需字段被拒；换传输方式协议字段不变（协议模块不 import 宿主特定代码）。
- [ ] AC-02：`fstar dispatch` 四角色命令仅准备/校验/登记，输出明确实际派发由宿主适配器完成；无任何输出暗示 shell CLI 已启动会话内子代理。
- [ ] AC-03：结果回收核对 dispatch 身份、当前基线（输入指纹未变）、授权范围（changed_paths ⊆ allowed_paths）、租约 token 后才经核心 API 写证据；任一不匹配拒绝写入并说明缺项。
- [ ] AC-04：持久任务协调者持租约、worker 回报续租、核心 check 独立性闸门成立（check producer ≠ delivery producer）；最小闭环无 task.json 时全部簿记静默跳过且不建文件。
- [ ] AC-05：并行分组按依赖+写入/共享资源冲突推导；冲突项串行、无冲突项并行；优先级不越过依赖。
- [ ] AC-06：check 交接后同范围 implement 写入停止（协议层标记 + 回收核验拒绝越界 changed_paths）。
- [ ] AC-07：对话/文件变更统一消息格式；转向能力按宿主实测分档（实时确认/检查点停止重派）；旧结果留历史不算当前通过。
- [ ] AC-08：派发失败最多自动重试 1 次且携带上次原因；仍失败进入 debug；环境阻塞不循环。
- [ ] AC-09：孤儿租约 continue 只读报告，用户决定接管/重派/放弃；不自动重派、不假报恢复。
- [ ] AC-10：editor 限定指定 doc 文件/条目，提交前基线哈希核对，冲突返回不覆盖。
- [ ] AC-11：两宿主派发方式实测并记录能力矩阵；未支持项列为降级，不写成功能保证。
- [ ] AC-12：dispatch/interrupt/doc-edit 子命令经 `register_commands`/`_fstar_module_handler` 约定接入 CLI，与 core/hooks 文件不冲突。

## 范围外

不实现：hooks 事件簿记（runtime-hooks 所有）、安装器/宿主资源放置（package-install）、工具能力绑定（tool-binding）、e2e 双宿主整体验证（e2e-verify）、第五角色或 learn 角色派发、AI 工具分类、自动依赖调度器（并行组从 plan 显式推导，不建全局调度器）。不复制 Trellis channel 源码，仅借鉴协议思路。

## 依据

- 父 `design.md` §3.7（派发协议）、§3.3（租约）、§3.2（证据回收）、§4.1（dispatch/interrupt/doc-edit 命令）、§4.5
- 父 `implement.md` §3 #5 验证清单、§4 集成验证 #17/#19
- `research/worker-adapter-protocol.md`（两宿主传输观察，实测起点）
- 核心实际 API：`src/fstar/tasks.py`（acquire/renew/release_lease、continue_task、state）、`src/fstar/evidence.py`（record/freshness/acceptance_status、delivery_snapshot）、`src/fstar/cli.py`（`register_commands`/`OPTIONAL_HANDLER_ATTR` 约定）

## Notes

- 父任务：`../10-25-fstar-workflow-design/`（需求总集、任务地图、最终集成验收）。
- 本子任务的详细技术设计见 `design.md`，执行计划见 `implement.md`（本 Trellis 子任务的 implement.md，非产品 plan.md）。
- core-commands 的整文件模式（`mode:"file"`）artifact_map 修复在途（workflow-content check 报告跨所有权缺陷）；本任务回收核验经核心 `snapshot/record` 走核心路径，不依赖该修复完成，但集成测试遇该路径时如实记录为上游受限项。
