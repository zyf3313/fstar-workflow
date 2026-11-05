# 派发协议实施计划

> 本文件是 **Trellis 子任务的 `implement.md`**。fstar 产品的任务执行产物为 `plan.md`，不得因本文名称生成产品 `implement.md`。

## 实施进度（2026-10-29，implement 轮 + 联合 check 轮）

RD-I1–RD-I6 已交付；联合独立 check（与 runtime-hooks 同批）已修复下述跨模块缺陷并补齐回归测试；RD-I7 能力矩阵已产出（live-delivery 级证据仍为 0 项，两宿主真实派发/转向/中断未验证，见 `research/dispatch-host-capabilities.md`）；RD-I8 联合检查已执行并自修。

- `src/fstar/dispatch.py` 已交付：协议层（payload/result/change 构建与校验、路径安全、editor/research 专属约束、prompt 首行规则、`build_worker_prompt` 纯函数、`adapter_invocation_note`）、登记层（持久任务协调者租约 + `dispatch_registered` 统一事件封套；session-only 静默跳过不落盘）、回收层（单一路径 `harvest`：身份/输入基线/范围/重放/租约；`stale_input` 返回 change message 不写过期结果；editor 按结果报告基线版本判 `baseline_conflict`；check 经核心 `_validate_check` 全链）、并行分组、检查交接（`meta.templates.dispatch_check_handoff` 任务持久化）、重试（1 次附 `prior_failure`，二次失败 `dispatch_failed_persistent`→fstar-debug；环境阻塞不重试）、interrupt/orphan（只读报告，复用核心 continue 行为）、CLI 注册（dispatch implement|check|research|editor|harvest|retry|orphan 子命令、interrupt、doc-edit）。
- cli.py 协调修改已完成：可选模块清单加入 `"dispatch"`。
- 联合 check 修复要点（详见本文件下方 check 记录与父进度）：输入基线 vs 期望输出的区分（合法写入不再一律 stale）；hooks worker-result 委托单一 harvest 路径、无登记 payload 不得写证据；重放防护任务持久化；失败/取消保留协调者租约（不孤儿化兄弟 worker）；嵌套子任务路径匹配按段前缀；`orphan` 收编为 `fstar dispatch orphan` 内部子命令（无新增顶层用户命令）。
- 旧「core file-mode artifact_map 修复在途、集成路径受限」的表述作废：该修复已在 79 项基线中存在（`evidence.py` 支持 `mode:"file"`），本次新增 `test_file_mode_artifact_map_baseline_roundtrip` 走真实 file-mode 派发基线往返并通过。静态语义内容/源模板缺口仍是 workflow-content 范围的开放项，不由 runtime 单测关闭。

## 当前状态与读取要求

本轮仅准备本目录 prd/design/implement 与两个 jsonl（2026-10-29）。已有第一版实施授权保持；未启动本子任务、未写产品代码、未执行 git。以下复选项是后续实施工作，不能视为已完成。

开始实施先完整 Read 父 `../10-25-fstar-workflow-design/{prd,design,implement}.md`（父 design 超 injection 上限，必须 Read 补齐全文）与本子 prd/design；再按 jsonl 所列规划/研究文档。核心源码不进注入清单，由执行者开工时自行 Read：`src/fstar/tasks.py`（租约/continue/state/事件封套）、`src/fstar/evidence.py`（snapshot/delivery_snapshot/record/新鲜度/独立性闸门）、`src/fstar/cli.py`（`_register_optional`/`OPTIONAL_HANDLER_ATTR` 注册约定与模块清单行）。core 的 file-mode artifact_map 修复已在基线中存在；file 模式集成用例已实跑（见上方进度），不再是"上游受限项"。

宿主能力为 **to-verify**：Claude Code/Codex 的实际派发机制、实时转向、中断、恢复、成本报告在实施期以本机宿主实测并记录到本目录 `research/dispatch-host-capabilities.md`（版本、事件/机制、样例、覆盖限制）；`research/worker-adapter-protocol.md` 仅是观察起点，其文末 check 用例审批契约已被父契约撤销，不得实现。

## 实施顺序

| ID | 工作与完成判据 | 依赖/并行 | 验证及文档责任 |
|---|---|---|---|
| RD-I1 | 只读核对 core 实际 API（`TaskService.acquire/renew/release_lease/continue_task/state`、`EvidenceService.snapshot/delivery_snapshot/record/invalidate/freshness/acceptance_status`、cli `_register_optional`/`OPTIONAL_HANDLER_ATTR`）与 hooks 的共享 schema/入口；登记差异，不改他人文件。 | 首先；只读 | design §7 待协调项落定（cli 模块清单加入 `"dispatch"`，与 hooks 的 `fstar.runtime` 互斥） |
| RD-I2 | `src/fstar/dispatch.py` 协议层：payload/result/change 构建与校验、路径安全、editor/research 专属约束、prompt 首行规则；纯函数无 IO。 | I1 | T1/T2；协议不 import 宿主代码 |
| RD-I3 | 登记层：DispatchService.register——持久任务协调者租约 + 统一事件封套登记；session-only 静默跳过不落盘。 | I2、core API 可用 | T3/T4 |
| RD-I4 | 回收层：harvest 四步核验（身份/基线/范围/租约）→ `EvidenceService.record`；check 全链、delivery 证据构建、stale_input 拒绝 + change message。 | I3 | T5/T6 |
| RD-I5 | 并行分组、检查交接标记、失败重试策略（1 次 + prior_failure）、interrupt/doc-edit 命令。 | I4 | T7/T8 |
| RD-I6 | `register_commands` 接入 CLI（dispatch/dispatch harvest/interrupt/doc-edit），`--json`、稳定错误码。 | I5 | T9；compileall + 全库回归 |
| RD-I7 | 宿主适配指引：payload→worker 提示词纯函数 + 适配调用说明输出（`dispatch_mode: "adapter"`）；两宿主能力档位实测记录。 | I2 后可与 I3–I6 并行（不同文件） | T10；实测记录含版本与覆盖限制，不虚构 |
| RD-I8 | 本任务整体独立 check（trellis-check），本范围自修并按影响回归；交付实测结果、未覆盖项与所有权报告。 | I6/I7；检查范围交接后停止实施写入 | 全部 AC、父 implement §3 #5 与 §4 #17/#19 相关项 |

实施按父协议交原生 implement 角色派发（trellis-implement）；协调者单写本文件进度，worker 回报不并发写。

## 测试矩阵

| ID | 场景与可观察结果 |
|---|---|
| T1 | payload 校验正负例：缺 schema/dispatch_id/role/baseline/allowed_paths 拒绝；坏 role 枚举、绝对路径/`..`、session-only 捏造任务路径、editor 缺 item_ids/baseline_sha256、research 越界路径均拒绝并给可定位 code/details。 |
| T2 | result/change 结构校验；change 消息含 change_id/来源/受影响条目与计划项/新旧指纹/动作。 |
| T3 | register：持久任务（临时目录真实 TaskService）取协调者租约、事件封套 `{id,at,source,type,data}` 合法（核心 validate_task 通过）；session-only 前后目录集合逐字节不变。 |
| T4 | 租约纪律：活跃他人租约拒绝；worker 不写 task.json；协调者有效回报续租 +30m（经 record）。 |
| T5 | harvest：dispatch_id/role 不匹配、输入指纹已变（stale_input + change message）、changed_paths 越界（scope_violation）、editor 基线冲突（baseline_conflict）、租约 token 失效/过期各拒绝且不写部分结果。 |
| T6 | 合法回收：implement result → delivery 证据入 task.evidence 且续租；check result 走核心 `_validate_check`（五态、run_id/environment、独立性 producer≠delivery）；worker done 不产生 acceptance。 |
| T7 | parallel_groups：依赖链、allowed_paths/shared_resources 交集、优先级不越依赖的确定性分组。 |
| T8 | 重试：失败自动重派 1 次且 payload 附 prior_failure；二次失败返回 dispatch_failed_persistent（debug 路由）；环境阻塞不重试。check 交接后同范围 implement 回收被拒，范围外继续。 |
| T9 | CLI：四角色 dispatch + harvest/interrupt/doc-edit 经 build_parser 实际调用；`--json` 错误形状稳定；未 init 目录 session-only 模式不建 `.fstar` 元数据；输出含 `dispatch_mode: "adapter"`，无任何"已启动 worker"表述。 |
| T10 | prompt 构造纯函数：首行 `Active task: <path>`/`session-only`、字段注入完整；宿主能力矩阵为实测记录（人工证据），不伪造单测。 |

负例不靠禁词机械匹配；语义正确性（协议字段是否满足父 §3.7、是否暗示 shell 可派会话代理）由独立 check 审查。

## 实际执行时的验证命令

- `PYTHONPATH=src python3 -m unittest discover -s tests`（含既有 78 项全库回归）
- `python3 -m compileall -q src/fstar tests`
- `PYTHONPATH=src python3 -m fstar dispatch implement --payload <fixture> --json`（临时项目 fixture，session-only 与持久任务两种）
- 两宿主实测：按 `research/dispatch-host-capabilities.md` 的记录模板执行真实派发/转向/中断样例，记录宿主版本与实际行为

## 回滚点

停止派发并修复适配器/协议模块；不回退主 Agent inline 生产代码；不删用户任务/证据数据；dispatch.py 为独立模块可整体摘除而不影响核心命令面（父 implement §5）。

## 收工核对（对应父 implement §2 收工）

1. 逐项执行本 PRD AC 与上述测试，保存真实命令/结果/环境/版本；未运行不记通过。
2. 独立 check；check 可修本范围生产/测试代码并回归。
3. 确认未私增顶层 task 字段、phase、扩展包、skills/hooks/roles、面向用户命令；协议 schema 变更先更新本 design 并与 hooks 协调共享消息字段。
4. 回写落实的设计细节与证据；宿主能力记录区分实测与推断。
5. 子任务完成保留在父 subtasks 树，不单独归档。
