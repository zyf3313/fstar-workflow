# 宿主派发能力矩阵（RD-I7 实测记录）

记录日期：2026-10-29。执行者：联合独立 check（trellis-check，runtime-dispatch + runtime-hooks 联合范围）。

## 证据等级（本文件区分，不混写）

1. **observed-schema（宿主二进制/schema 观察）** —— 在已安装宿主二进制或其生成 schema 中确认存在的字符串/枚举/结构。证明宿主定义了该机制，**不证明** fstar 已注册、事件已投递、或运行中可用。
2. **fixture-test（本仓库测试）** —— 依赖注入/临时目录的确定性测试。证明 fstar 侧逻辑正确，不证明宿主行为。
3. **live-delivery（真实宿主内端到端）** —— 在真实宿主会话中注册 hook 并观察事件投递/子代理派发/转向。**截至本记录：0 项。**

## 本机宿主版本

| 宿主 | 版本 | 观察来源 |
|---|---|---|
| Claude Code | 2.1.312 | `claude --version` 输出 |
| codex-cli | 0.165.0 | `codex --version` 输出 |

## 能力矩阵

| 能力 | 等级 | 事实 | 剩余 e2e 检查（必做） |
|---|---|---|---|
| Claude Code hook 事件名 SessionStart / PreToolUse / PostToolUse / SubagentStart / SubagentStop / Stop | observed-schema | 二进制内字符串存在；本仓库 `.claude/settings.json` 已有 SessionStart/PreToolUse 注册（Trellis 自身使用，非 fstar） | live-delivery：fstar 条目注册后真实事件投递一次并核对 payload |
| Claude Code Task/Agent 工具子代理派发 | observed-schema + 间接使用 | fstar 项目自身由 Claude Code 原生子代理（trellis-implement 等）开发，派发机制已被本会话实际使用（本任务即由子代理执行） | live-delivery：fstar 四角色经宿主 Agent 工具派发并回收 `fstar.dispatch.result.v1` |
| Claude Code 运行中转向（steer/中断后传达变更） | **unknown** | 二进制未观察到子代理级实时转向 API 字符串；探针结论见父 project-context（仅证明原生子代理可被中途消息影响，为会话级实测，未形成可调用契约） | live-delivery：对运行中 worker 送达 change message 并确认 ack；不支持则按 checkpoint-stop 降级 |
| Codex HookEventName 枚举（sessionStart/preToolUse/postToolUse/subagentStart/subagentStop） | observed-schema | 实施者记录其 0.165.0 生成 app-server schema 含该枚举 | live-delivery：`.codex/hooks.json` 真实注册 + 一次事件投递，payload 形状核对 |
| Codex app-server `turn/steer` / `turn/interrupt` / `thread/queue/add` | observed-schema（上游研究稿 `../10-25-fstar-workflow-design/research/worker-adapter-protocol.md` 观察） | 协议存在，fstar 未接入，双向 RPC 握手与反向请求应答是否可由 fstar 适配器满足未验证 | live-delivery：适配器实装并实测一次转向 |
| fstar CLI 不能启动宿主会话内子代理 | **设计事实** | `dispatch_mode: "adapter"` 由协议保证；CLI 只准备/校验/登记 | 无（协议层，测试覆盖） |

## 已降级/未证实项（不写成功能保证）

- **SubagentStop（两宿主）不能携带派发结果消息**：worker-result 的主路径是 runtime-dispatch 回收边界（`fstar dispatch harvest` / hooks 委托同一路径）；宿主事件即使投递也只作簿记信号。本仓库测试已按此实现。
- **Codex postToolUse payload 的文件路径键**：schema 未暴露，`verified: false`，doc path 提取依赖一次真实 codex 运行核对；此前提下回退路径（`fstar evidence invalidate` + 核心读取边界重算）已实现并测试。
- **运行中转向**：当前实现默认 checkpoint-stop 档位；realtime-steer 档位在 live-delivery 证据产生前不得宣称可用。
- **成本/进度回报**：两宿主均无观察证据，未实现。

## 必做的剩余 e2e 检查（归 e2e-verify 子任务）

1. Claude Code：注册 fstar 四条 hook 条目（package-install 执行写入），观察 SessionStart 投递与注入文本进入会话。
2. Claude Code：经宿主 Agent 工具实际派发 implement/check 角色 worker，回收 `fstar.dispatch.result.v1`，经 `fstar dispatch harvest` 写入证据。
3. Claude Code：实测运行中转向是否可送达（realtime-steer 档位判定），不可用则记录降级事实。
4. Codex：`.codex/hooks.json` 注册形态真实写入后事件投递核对（hooks.json 键大小写、payload 形状）。
5. Codex：等效子代理派发机制实装后回收一次结果（app-server thread 或宿主内子代理，按实际支持）。
6. 两宿主各做一次 worker 失败→debug 路由与一次 cancelled→变更传导检查点路径观察。

## 与既有"上游缺陷"记录的更正

runtime-dispatch 旧 implement.md/design.md 中「core file-mode（mode:"file"）artifact_map 修复在途、集成路径受限」的说法已过期：该修复在 79 项基线中已存在（`src/fstar/evidence.py` 现支持顶层 `mode:"file"` 持久化、file 粒度快照与失效），本次检查新增 `test_file_mode_artifact_map_baseline_roundtrip` 走真实 file-mode 派发基线往返，通过。后续文档不得再引用"在途/受限"表述。
