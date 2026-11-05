# Worker 适配器协议：Claude Code 与 Codex 实测

状态：调研结论，供协议设计使用。非实现授权。
来源标注：**[code]** 读适配器源码 / **[cli]** 实测 CLI 帮助或二进制 / **[schema]** 生成的协议 schema / **[推断]**

核查版本：Claude Code 2.1.310，codex-cli 0.163.0，Trellis 0.6.17。

## 一、两个后端的最小事实

### Claude Code **[code]** `adapters/claude.js:200-224`

| 项 | 实现 |
|---|---|
| 启动 | `claude -p --input-format stream-json --output-format stream-json --permission-mode bypassPermissions --dangerously-skip-permissions --verbose [--resume <id>] [--model M]` |
| 输出 | NDJSON，每行一帧 |
| 解析 | `system+init`→存 session_id；`assistant`→text/tool_use；`result`→done 或 error |
| 中途指令 | **写 stdin**：`{"type":"user","message":{"content":[{"type":"text","text":...}]}}` |
| 中断 | `{"type":"control_request","subtype":"interrupt"}` + user 帧 —— **真中断** |
| 完成 | 收到 `result` 帧 |
| 恢复 | 原生 `--resume <sessionId>` |
| 反向请求 | 无 |
| 成本 | `total_cost_usd` / `num_turns` / `duration_ms` |

### Codex **[code]** `adapters/codex.js:529-534` + **[cli]** + **[schema]**

| 项 | 实现 | 与 Claude 的差异 |
|---|---|---|
| 启动 | `codex app-server`（持久 JSON-RPC 2.0 over stdio） | **根本不同**：不是单向输出泵，是双向 RPC |
| 握手 | 必须：`initialize` → 等 150ms → `thread/start` → 轮询 ≤30s 拿 threadId | Claude 无握手，就绪即 true |
| 中途指令 | `turn/start{threadId,input[]}` | 需先有 threadId |
| 中断 | **Trellis 是假的**：不发 `turn/interrupt`，而是给文本加前缀 `[GRID INTERRUPT ...]` 再发新 `turn/start`，本地标记旧轮作废 | Trellis 在此处弱于协议能力 |
| 反向请求 | **必须应答**：`mcpServer/elicitation/request` 等，否则卡住 | Claude 无反向通道 |
| 完成 | `turn/completed`，**可能早于最终 agentMessage** → 需要 latch | Claude 的 `result` 在文本之后 |
| 流式 | 原生 `item/agentMessage/delta` | Claude 需 `--include-partial-messages`（Trellis 未用） |
| 恢复 | `thread/resume` **存在但 Trellis 未接** | Claude 原生可用 |
| 成本 | `thread/tokenUsage/updated` 被丢弃 → done 负载为空 | Claude 有完整成本 |
| 系统提示 | `thread/start.developerInstructions` | Claude 用 argv / 文件 |

### 协议里存在但 Trellis 未用的能力 **[schema]**

- `turn/steer{threadId, expectedTurnId, input[]}` —— **真正的中途转向**，前提是 turn id 匹配
- `turn/interrupt{threadId, turnId}` —— 真正的中断
- `thread/queue/add{threadId, input, clientUserMessageId}` —— 排队到后续
- `thread/injectItems{threadId, items}` —— 注入原始 Responses-API 条目

**结论：自研时在 Codex 上可以做得比 Trellis 更正确**（用 `turn/steer` / `turn/interrupt`，而不是文本前缀伪装）。

## 二、事件模型

适配器只负责产出 **4 种事件** **[code]** `types.d.ts:8-32`：

```
message{text}
progress{detail{...自由结构}}
done{...}
error{message,...}
```

其余事件由 supervisor 补：`spawned`、`killed`、`turn_started`、`turn_finished`、`interrupted`、`supervisor_warning`。seq/ts/by 也由 supervisor 添加。

SideEffect 类型：`persistSessionId` / `persistThreadId` / `reply[]` / `resolved[]`。其中 `reply[]` 直接写回 worker stdin —— 这是 Codex 反向请求的应答通道。

**注意**：`progress.detail` 是松散结构，两个后端的工具词汇不同，所谓"归一化"实际并未归一。

## 三、最小适配器接口（提案）

标记：**F** = 被 Codex 强制 / *F* = 自由选择

```
provider: string                                  // F  二进制名
buildArgs({model?, systemPrompt?, systemPromptFile?, cwd, resume?}): string[]
                                                  // F
createCtx(): C                                    // F  Codex 需要 RPC id 表；Claude 可返回 undefined
handshake?({child, ctx, view}): Promise<void>     // F  initialize + thread/start
isReady(ctx): boolean                             // F
parseLine(line, ctx): {events, side?}             // F
encodeUserMessage(text, ctx): string              // F
encodeInterrupt?(text, ctx): string               // F
reply(reqId, result): string                      // F  Codex 反向请求应答
onSessionId(id): void                             // F
kill?(child)                                      // 自由：默认共用杀进程阶梯
```

**自由选择的部分**：事件词汇、progress 结构、系统提示投递方式、沙箱参数、恢复机制。

## 四、不可移植能力与降级

| 能力 | Claude | Codex | 运行时降级 |
|---|---|---|---|
| 中途转向 | interrupt + user 帧（真实） | `turn/steer` 存在，Trellis 未用 | 若适配器不实现 steer：等本轮结束再发；最差杀进程重启 |
| 上下文恢复 | `--resume` 原生 | `thread/resume` 存在但未接 | 重派并重放提示，不保证连续性 |
| 成本统计 | 完整 | 被丢弃 | 可选 `usage` 事件，缺失则省略 |
| 流式文本 | 需额外 flag | 原生 | Claude 仅在结束时给消息 |
| 反向请求 | 无 | **必须有应答** | 适配器必须实现 responder，否则轮次卡死 |
| 权限/沙箱 | argv | 每 thread 的 RPC 参数 | 抽象成适配器级「权限策略」结构 |
| 结果顺序 | 文本先于 result | completed 可能先到 | 适配器保证 message 先于 done |
| 递归防护 | 不适用 | `features.multi_agent=false` | 按适配器禁用 |

## 五、worker 权限策略（已确认）

用户确认：**完全绕过，与 Trellis 一致**（`--permission-mode bypassPermissions --dangerously-skip-permissions`）。

理由：worker 是非交互进程，无法应答权限提示；中断等待会破坏执行闭环。

### 必须记录的风险

- 用户在 `~/.claude/settings.json` 设置的 `deny` 规则（`rm -rf`、`git reset --hard`、`git clean -f` 等）**对 worker 全部失效**。
- 这是显式接受的取舍，不是遗漏。

### 不改变该决定的前提下可做的缓解

1. **派发提示写明写入范围**：worker 只应修改任务声明的文件。这是 prompt 级约束，不是权限级，属于事后可检查而非事前阻断。
2. **git 作为恢复手段**：fstar-execute 的回滚路径依赖 git 状态，不是权限拦截。
3. **检查环节核对改动范围**：`fstar-check` 的「范围纪律」项应核对实际改动是否超出声明范围，超出即报问题。
4. **不在 worker 提示中鼓励破坏性操作**；破坏性命令仍需主 Agent 层面确认。

明确不做的：不为此加自定义 hook 拦截（第一版不开放 hooks），不改宿主权限配置。

## 六、未确定

1. Codex 在已有活跃 turn 的 thread 上再发 `turn/start` 是拒绝还是排队 —— 未实测。协议提供 `thread/queue/add` 正是为这种情况。
2. Trellis 未发 JSON-RPC `initialized` 通知却工作正常，推测该通知可选，未对照规范验证。
3. Claude 官方文档在本环境不可达（`code.claude.com` 被拦），Claude 相关结论均来自已安装二进制与 Trellis 源码，属**观测**而非**文档**。

## 七、对协议设计的影响

最关键的一条：**Codex 要求双向 RPC 客户端（id 关联、握手、反向请求应答），Claude 只需要行解析器。**

因此协议不能假设"后端都是单向输出泵"。事件模型必须允许：

- 适配器主动向上游请求（反向请求）
- 运行时向下游应答（`reply`）
- 完成信号与最终文本可能乱序（需 latch）

这三条是 Codex 强制的，Claude 可以全部忽略。

## 当前 check 派发契约（2026-10-28 同步）

上文宿主/传输观察不授予角色额外写权限。当前 v1 派发层按 `policy-decisions.md` 采用宿主原生子 Agent。check 派发/恢复前必须核验 `doc/test-cases.md` 已获用户 `approved` 且指纹新鲜，注入批准范围、稳定用例 ID、版本/指纹与可核验审批证据。用例由 AI 先拟草案供审阅，或用户直接提供/修改；供稿不自动等于批准。

check 只可按稳定 ID 编写/补充批准范围内的单元测试（必要时集成测试）并运行，禁止改生产代码；生产缺陷交 fixing/implement 修复。交付 `acceptance/check-<n>.md` 须逐用例映射测试代码路径/测试标识与实际命令、结果、运行证据，含交付/用例版本、指纹、环境和 run id；生成用例或 done 事件不等于测试通过。用户改用例使对应 review/check evidence stale；传导要求在途 check 对齐，回收再次核验指纹，旧结果不能写作新鲜证据。
