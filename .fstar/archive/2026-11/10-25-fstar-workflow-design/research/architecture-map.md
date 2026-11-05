# fstar 工作流架构总图

> **状态（2026-10-29）**：本文件按更早口径绘制，资源数量与命名已被取代：skill **12** 个（`fstar-archive` 取代 `fstar-finish`；`fstar-doc` 收窄为只维护任务 `doc/`）；`implement.md` → **`plan.md`**；`test-cases.md`、测试评审包**暂缓**；`review-log.md` **已移除**；`knowledge/decisions/` 删除；check 可自修生产代码。分层思路、矩阵与调用时序仍可参考，具体数量与命名以 `prd.md` 为准。

状态：规划草案，2026-10-26。**不构成实现授权。**

本文件把分散在 `research/` 各文件里的状态机、hooks、skills、agents、templates、目录结构重新汇成一张对照图，用于评审时逐项核对。

## 信息来源

| 图中内容 | 来源文件 |
|---|---|
| 阶段、证据、租约、归档判据 | `docs/project-context.md`「状态机结论」 |
| 目录与文件归属 | `research/directory-proposal.md` |
| hooks / skills / templates 全量 | `research/hooks-skills-templates.md`（含过时项，见文末第八节） |
| skills 修正版与缺口分析 | `research/skills-detailed.md` |
| 协作运行时与双平台协议 | `research/worker-adapter-protocol.md` |
| 可复用 / 需替换 / 需新增 | `research/three-lists.md` |
| 优先级、更新、记忆、依赖 | `research/policy-decisions.md` |

---

## 一、总体分层

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ① 触发层  Hooks（仅 A/B 两类为真 hook）                                      │
│    session-context │ turn-context │ worker-context │ worker-result │ doc-change │
│    职责：宿主事件发生时的定位、提示、提醒                                    │
│    边界：只做「找到」，不做「判定」                                          │
│    非 hook（不在此层）：C after_* 回调 │ D 会话身份解析 │ E linear_sync      │
└──────────────────────────────────────────────────────────────────────────────┘
        │ 注入：当前任务 / 阶段 / 阻塞 / 待办提醒
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ② 编排层  Agent 角色                                                         │
│    主 Agent：与用户对话 · 判断阶段 · 调用命令 · 决定是否派发（非角色卡）     │
│                                                                              │
│    research ── 调研 · 定位 · 选型依据                                        │
│    implement ── 实施 · 修复                                                  │
│    check ── 已批准用例 → 写测试 · 运行 · 出证据                              │
│    editor ── 指定 doc 文件/条目修改                                          │
│                                                                              │
│    派发传输（2026-10-27 已定：原生优先）：                                   │
│      v1 宿主原生子 Agent（Claude Code Task/Agent、Codex）                    │
│      协议自研 · 适配器自研 · 对等运行时后置                                  │
└──────────────────────────────────────────────────────────────────────────────┘
        │ 调用能力
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ③ 能力层  Skills（核心 4 自动触发 + 9 协商路由，共 13）                       │
│    核心：execute │ check │ debug │ help（常驻预算，支撑最小闭环）             │
│    协商：init │ clarify │ continue │ finish │ learn │ recall │ tools │ doc   │
│          │ [ui-design 可选]（扩展包同意后由主 Agent 显式路由）                │
│    只加载命中的 SKILL.md；references/ 按当前子任务再读                       │
└──────────────────────────────────────────────────────────────────────────────┘
        │ 需要外部能力时查绑定
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ④ 工具层  Tools 【新】                                                       │
│    5 个能力维度：code-structure │ web-research │ knowledge-retrieval         │
│                 data-access │ test-execution                                 │
│    能力契约（fstar 定，判定要点+降级路径）→ 绑定（用户配）→ 实际工具（外部） │
│    分类器三层：L1 探测 → L2 按能力匹配 → L3 验证；只提议，不自动安装         │
└──────────────────────────────────────────────────────────────────────────────┘
        │ 写产物时套用骨架
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ⑤ 产物层  Templates                                                          │
│    doc×4 │ task×3 │ knowledge×3 │ entry×2 │ optional×4                               │
│    是文档骨架：不是命令、不是授权记录、不是自动触发器                        │
└──────────────────────────────────────────────────────────────────────────────┘
        │ 落到
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ⑥ 存储层  目录结构                                                           │
│    用户级 ~/.fstar/ │ 项目级 <项目>/.fstar/ │ 任务级 tasks/<id>-<名称>/      │
│    项目级新增 .fstar/knowledge/（长期知识）· tools.yaml（能力绑定）          │
└──────────────────────────────────────────────────────────────────────────────┘
        │ 任何写入必须经过
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ⑦ 底座  最小闭环内核 + 持久任务包状态机（唯一权威，Agent 自觉不算数）        │
│    最小闭环（默认，不落盘，任何目录可用）：                                  │
│      澄清目标 → 执行 → 基础检查 ↔ 修复 → 用户确认                            │
│      会话内节点 clarifying/executing/checking/fixing/awaiting_user 仅路由     │
│    持久任务包启用后（7 态状态机）：                                          │
│      7 阶段 + fixing 闭环 + dropped 终态 │ blocked 为阶段属性                │
│      phase(标量) · evidence(可失效) · ownership(租约/心跳)                   │
│    硬拒：Agent 写 done/archived · drafting→implementing · stale 证据下进验收 │
└──────────────────────────────────────────────────────────────────────────────┘
```

一句话概括：**Hooks 负责「让 Agent 知道现在该干什么」，Skills 负责「怎么做」，Agents 负责「谁干」，Templates 负责「产物长什么样」，目录负责「存到哪」，核心命令负责「准不准」。**

**最小内核 + 扩展包（2026-10-28 定案）**：以上七层描述的是**全部加载后**的完整形态。fstar 的底座是最小闭环内核（`澄清 → 执行 → 基础检查 ↔ 修复 → 用户确认`，不落盘、任何目录可用）；六个扩展包——规划评审 / 测试评审 / 持久任务 / 多 Agent / 项目治理 / 工具能力——按需协商加载，各包授权独立、默认整包可裁剪、拒绝后无新事实不重复问。7 态状态机是**持久任务包的状态机**，不是底座。详见父任务 `prd.md` §12 与 `design.md` §2.4。

三条不可破的边界：

1. **⑤ → ⑥ 单向强制。** 所有状态写入走 `fstar task state set`，命令内部校验转移合法性；Agent 不能直写 `task.json`。
2. **① Hooks 不独立判定阶段。** `doc-change` 调核心命令做指纹/stale 簿记；批准、证据有效性及转移判定在 ⑦ 底座。
3. **③ 的方法细节不写两遍。** 角色卡只写权限、输入契约、交付格式、禁止事项；方法细节在 skill 的 `references/`。

---

## 二、六个维度的职责边界

| 维度 | 负责 | 明确不负责 |
|---|---|---|
| **Hooks** | 宿主事件发生时定位上下文、触发提醒、注入最小信息 | 状态转移校验、耗时调研、代替用户验收 |
| **Skills** | 告诉 Agent 一类工作怎么做 | 保证状态转移合法、代替命令 |
| **Agents** | 规定执行者权限、输入契约、交付格式、禁止事项 | 重复写方法细节（方法在 skill reference） |
| **Templates** | 产物骨架 | 执行命令、授权记录、自动触发 |
| **目录结构** | 内容归属与持久化 | 运行状态（分离在 `runtime/`） |
| **核心命令** | 校验批准、版本、证据、租约、状态转移 | 语义判断（语义在 skill / agent） |

---

## 三、资源维度全量清单（7 节）

### 3.1 Hooks（五类机制，只有 A/B 是真 hook）

此前把五类并列在同一标题下，容易读成「fstar 要提供 7 个 hook」。实际只有 **A / B** 是宿主事件 hook。

| 类 | 名称 | 本质 | 是否内置 | 第一版 | 与 Skill 的关系 |
|---|---|---|---|---|---|
| **A** | 宿主事件 hook | 宿主在固定事件调用固定脚本 | 内置 | ✅ | 工作流环节 → 有对应 skill |
| **B** | 运行时事件 | 运行时产出的完成 / 失败 / 取消事件 | 内置 | ✅ | 工作流环节 → 有对应 skill |
| **C** | 核心命令后置回调 | task 命令成功后跑 config 里配的任意 shell | 机制存在 | ❌ 不开放 | 扩展点 → 无 skill |
| **D** | 会话身份解析（非 hook） | 被多处调用的解析函数 | 内置基础设施 | ✅ | 基础设施 → 无 skill |
| **E** | 外部集成示例 | Trellis 提供的模板 | 不提供 | ❌ 不带 | 外部集成 → 无 skill |

#### A. 宿主事件 hook（内置，第一版保留）

| Hook | 触发事件 | fstar 行为 | 对应 Skill | 绑定方式 | 落盘位置 |
|---|---|---|---|---|---|
| `session-context` | SessionStart（startup / clear / compact） | 识别用户级·项目级入口，定位当前会话任务，摘要 + 规则指针 | `fstar-continue` | 软触发 | `runtime/sessions/<id>.json` |
| `turn-context` | UserPromptSubmit（每轮输入） | 刷新阶段、阻塞、待验收 / 待归档提示 | `fstar-continue`（巡检同源） | 软触发 | `runtime/reminders.json` |
| `worker-context` | PreToolUse Task / Agent（派发前），或派发包装入口 | 按角色注入任务、rules/spec、修订与版本/指纹；check 必含已批准用例稳定 ID、范围、指纹及用户审批证据 | `fstar-execute` / `fstar-check` | **硬绑定** | 读 `implement.jsonl` / `check.jsonl` |

| `doc-change` | PostToolUse Edit/Write，命中 `doc/*.md` | 调核心命令重算指纹/标 stale/记事件并传导；用例变更在 drafting 也使已有 review/check evidence stale；不跑测试、不写报告 | `fstar-doc` | 软触发 | `task.json.events[]` / evidence / review 投影 |

#### B. 运行时事件（内置，第一版保留）

| 资源 | 触发点 | fstar 行为 | 对应 Skill | 绑定方式 | 落盘 |
|---|---|---|---|---|---|
| `worker-result` | 运行时 done / error / killed | 保存交付引用，安排检查或标记待处理（**worker done ≠ 任务验收**） | `fstar-check` | 软触发 | `task.json` 事件 + `acceptance/` |

#### C. 核心命令后置回调（机制存在，第一版不开放）

源码已核实 4 个调用点：`task_store.py:710`（after_create）、`task.py:254/268`（after_start）、`task.py:292`（after_finish）、`task_store.py:1457`（after_archive）。配置在 `.trellis/config.yaml:36-51`，**默认全部注释掉**。传入 `TASK_JSON_PATH`，失败只打印警告、不阻断主操作。

**这是任意 shell 命令执行入口** —— 宿主 hook 是「宿主在固定事件调固定脚本」，这个是「用户在配置里写命令」。用户已决定第一版不开放自定义 hooks，因此该机制不提供。

#### D. 会话身份解析（不是 hook）

`active_task.py:68-121` 的解析链：

```
TRELLIS_CONTEXT_ID（显式覆盖，hook 传给子进程用）
  → hook payload（宿主传的 session id）
  → 已验证平台环境变量（21 平台审计，其中 12 个无验证名）
  → 30s shell-ticket 桥（AI 无法传环境变量时的兜底）
```

它**依赖** hook（hook 把 `TRELLIS_CONTEXT_ID` 传给子进程），但**本身不是 hook**，是一段被多处调用的解析函数。职责也不同：它解决「我是哪个会话」，是所有命令的前提，不属于任何单个工作流环节。

#### E. 外部集成示例（不提供）

`.trellis/scripts/hooks/linear_sync.py:6-9` 的文件头写明：由 `after_*` 回调调用，或手动 `sync`。把任务事件同步到 Linear，依赖外部 `linearis` CLI 与 `.trellis/hooks.local.json`。

Trellis 把它放在 `scripts/hooks/` 目录下，容易误读成「默认启用 hook」。实际定位是**给用户抄的模板**。第一版不带。

#### 关键：hook 不「对应」skill

正确关系是 **hook 提供判断依据，skill 由 description 触发**，不是硬绑定：

```
Hook（时机） ──注入上下文──▶ 主 Agent ──读到内容──▶ 触发某个 Skill
                                           （靠 description 匹配，不是 hook 写死）
```

例：`session-context` 注入「当前任务 + 阶段」→ 主 Agent 读到 `awaiting_acceptance` → 匹配到 `fstar-finish` 的 description → 调用。

**唯一例外是 `worker-context`**：必须按 role 分流（implement 角色注入实现上下文、check 角色注入检查清单），因为派发时角色已确定，属硬绑定。

所以「hook 是否都对应一个 skill」的答案是：**对应「工作流环节」的有，对应「基础设施 / 扩展点」的没有。**

#### 第一版明确不做

| 不做项 | 触发点设想 | 理由 |
|---|---|---|
| 会话结束自动总结 / 沉淀 | Stop / SessionEnd | 自动全量总结制造噪声，退出不一定可靠触发；由 finish/learn 主动完成 |
| 每次文件修改后自动检查 | PostToolUse | 频繁测试、反复写报告干扰执行；在交付和变更检查点验证 |
| 自动提交 / 推送 / 归档 | 会话结束或 worker done | 容易把技术完成误当作用户授权 |
| 独立归档提醒 hook | — | 由 session-context、turn-context 和显式 continue/finish 调同一巡检逻辑 |
| 任意自定义 shell hook | — | = C 类不开放 |
| 外部 issue 系统同步 | — | = E 类不带 |

### 3.2 Skills（核心 4 自动触发 + 协商路由 8 + 可选 1，共 13）

> ✅ `hooks-skills-templates.md` 已同步（2026-10-27），与 `skills-detailed.md` 一致：**调研是 Agent，不是 Skill**。
> ✅ 2026-10-27 新增 `fstar-tools`（通用入口 11 个）。
> ✅ 2026-10-27 新增 `fstar-doc`（文档维护与一致性），通用入口变 **12 个**（加可选 UI 共 13 个，**13 为技能总数上限**）。
> ✅ **2026-10-28 skill 分层**：核心 4 个自动触发（#3 execute、#4 check、#7 debug、#10 help）；其余 9 个（#1/2/5/6/8/9/11/12/13）为协商路由——对应扩展包获用户同意后由主 Agent 显式调用，可配 `skillOverrides` 降 listing 占用。总数仍 13。下表「分层」列标注归属。

| # | Skill | 触发 | Agent | 核心命令 / 状态转移 | 模板 | 落盘位置 |
|---|---|---|---|---|---|---|
| 1 | `fstar-init` | 进入未接入项目且确定持续开发；或整理刷新规范 | 主 | `fstar project init` + 工具探测（L1/L2）→ 绑定提案 | entry/project-index、knowledge/spec | `.fstar/{index.md,config.yaml,.gitignore}`、`specs/`、`tools.yaml` |
| 2 | `fstar-clarify` | 需求不清、新功能、范围变更、需技术设计 | 主 + research | `task create` → `state set drafting→planned` | doc/prd、doc/design、task/implement | `tasks/<id>/doc/{prd,design}.md`、`implement.md`、`research/`、`subtasks/` |
| 3 | `fstar-execute` | `planned` 且用户确认启动；实施中需求变更 | implement | `state set planned→implementing` + 取租约 | — | 代码变更、任务事件 |
| 4 | `fstar-check` | 实施交付后；修复后复查；需求变更致证据失效 | check | `implementing→checking`；`checking→fixing`；`→awaiting_acceptance`（需用户批准与证据新鲜；写测试前即校验） | doc/test-cases、task/check | `doc/test-cases.md`、测试代码、`acceptance/check-<n>.md` |
| 5 | `fstar-continue` | 用户说继续 / 恢复；打开项目；多候选任务 | 主 | `inspect` + 租约检查 | — | `runtime/sessions/`、`runtime/reminders.json` |
| 6 | `fstar-finish` | `awaiting_acceptance`；用户要求收尾 | 主 | `awaiting_acceptance→done`（仅用户）→ `archived`（判据全满足） | — | `acceptance/acceptance-<n>.json`、`archive/<年月>/` |
| 7 | `fstar-debug` | 同问题反复失败；根因不明；检查多次不过 | 主 + implement | 回退到 `drafting`（带原因 + stale + 释放租约） | — | `research/` 或 `design.md` |
| 8 | `fstar-learn` | 用户说「记住」；主动识别到可复用经验；收尾时 | 主 | — | knowledge/rule、knowledge/memory、knowledge/spec | `~/.fstar/rules/`、`~/.fstar/memory/`、`.fstar/specs/`、`.fstar/knowledge/` |
| 9 | `fstar-recall` | 「上次怎么做的」「之前讨论过吗」 | 主 + research | — | — | 只读（含 `.fstar/knowledge/`） |
| 10 | `fstar-help` | 用法、配置、定制、故障排查 | 主 | — | — | 只读 |
| 11 | `fstar-tools` | 需要某能力维度；初始化时；绑定失效；用户要换工具 | 主 | 查绑定 → 按需三层验证 → 调用 → 记录 → 缺口走降级 | — | `tools.yaml`、`runtime/tool-status.json`、检查报告 |
| 12 | `fstar-doc`（2026-10-27 新增） | 讨论中要改文档；评审意见要落到文档；定点修改（「把 R-003 改成…」） | 主 + **editor** | `fstar doc check` + `fstar evidence invalidate --file` | — | `tasks/<id>/doc/*.md` |
| 13 | `fstar-ui-design`（可选） | 有实际界面 / 交互需求 | 主 | — | optional/ui-baseline、optional/ui-feature | `specs/ui-baseline.md` 或 `design/ui-feature.md` |

**每个 Skill 的 `references/`**（按需加载，不预载）：

| Skill | references |
|---|---|
| `init` | onboarding、spec-bootstrap |
| `plan` | clarification、design-profiles |
| `execute` | before-dev、dispatch、changes、capability-discovery |
| `check` | testing、document-consistency |
| `debug` | root-cause |
| `learn` | knowledge-routing |
| `recall` | history-sources |
| `help` | layout、configuration |
| `ui-design` | ui-design |

### 3.3 Agent 角色（4 角色卡 + 主 Agent）

| Agent | 输入 | 输出 | 禁止 | 对应目录 |
|---|---|---|---|---|
| `research` | 调研问题、任务路径 | `research/<主题>.md`（每主题一份） | 改代码、改 spec、写其他任务目录 | `tasks/<id>/research/` |
| `implement` | PRD、design、implement、context 清单、specs | 代码变更、实施交付说明 | git commit / push / merge、判定任务完成 | 工作区 + 任务事件 |
| `check` | 开发完成后生成逐条目/场景链用例草案；用户 approved 且指纹新鲜后写测试并运行 | 用例范围内单测/必要集成测试 + 实际运行 + 用例→代码→证据映射 | 改生产代码、未批准即写测试、替用户验收、扩大范围重构 | 测试代码 + `tasks/<id>/acceptance/` |
| `editor` | 指定文件/条目与修改要求 | `doc/*.md` 的定点修改 + diff 摘要 | 改范围外内容、擅改 ID 或评审结论、改代码 | `tasks/<id>/doc/` |

主 Agent 不计入四张角色卡：它是宿主里的主会话，负责与用户对话、判断阶段、调用核心命令、决定是否派发。

**派发传输：v1 用宿主原生子 Agent（2026-10-27 已确认）**

协议由 fstar 定义、适配器由 fstar 实现；对等进程运行时**后置**，不是放弃。

| 路径 | 机制 | v1 状态 | 优势 | 代价 |
|---|---|---|---|---|
| **宿主原生子 Agent** | Claude Code `Task`/`Agent`、Codex `SubagentStart` | ✅ **v1 采用** | 零额外进程、上下文同源、hook 注册点单一 | 平台相关、消息送达有延迟（下一工具轮次）、跨会话恢复未验证 |
| 自研协作运行时 | 对等进程 + `events.jsonl` + 适配器 | ⏸ 后置 | 平台中立、可重放、可接管、Codex 真 `turn/interrupt` | 1,670–2,310 行；两套语义并存 |

理由：四个差异化能力（验收闸门、证据失效、归档提醒、全局记忆）**都不在派发层**；原生代码量小 3–5 倍；协议抽象对了实现可替换。

**必记风险**：跨会话 worker 恢复在原生方案下未验证。若不可用，v1 接受「重派」降级，`fstar-continue` 需写明 `orphaned` 的首选动作从「唤醒原执行者」降级为「重派」。详见 `policy-decisions.md`。

### 3.4 Templates（16 份，2026-10-27 调整）

| 类别 | 模板 | 产物位置 |
|---|---|---|
| doc×4 | `prd.md` | `tasks/<id>/doc/prd.md`（评审稿·需求） |
| doc | `design.md` | `tasks/<id>/doc/design.md`（评审稿·技术方案） |
| doc | `test-cases.md` | `tasks/<id>/doc/test-cases.md`（评审稿·测试用例） |
| doc | `review-log.md` | `tasks/<id>/doc/review-log.md`（需求变更/技术方案变更/用例审阅的变更留痕投影，不手改） |
| task×3 | `implement.md` | `tasks/<id>/implement.md`（复杂任务；仅 AI） |
| task | `research.md` | `tasks/<id>/research/<主题>.md`（仅 AI） |
| task | `check.md` | `tasks/<id>/acceptance/check-<轮次>.md` |
| knowledge×3 | `rule.md` | `~/.fstar/rules/<主题>.md` |
| knowledge | `memory.md` | `~/.fstar/memory/<主题>.md` |
| knowledge | `spec.md` | `.fstar/specs/<主题>.md` |
| entry×2 | `user-index.md` | `~/.fstar/index.md` |
| entry | `project-index.md` | `.fstar/index.md` |
| optional×4 | `exploration.md` | `research/exploration.md`（仅重要选型） |
| optional | `review-change.md` | `research/change-<序号>.md`（仅大范围变更） |
| optional | `ui-baseline.md` | 项目 UI 基线 |
| optional | `ui-feature.md` | `tasks/<id>/design/ui-feature.md` |

**评审稿模板的语义槽位**（2026-10-27 用户确认，约束强度 = 少量槽位 + 稳定条目 ID）：必填 `artifact_type` / `version` / `review_state` / `author` / `date` / `reviewer`，条目须有唯一稳定 ID 与关联；**章节、布局、语言、图示、ID 写法全部归用户**，自定义模板通过 `templates/<name>.mapping.yaml` 对接。解析优先级：任务显式指定 > 项目模板 > 用户模板 > 安装包默认。

**已合并掉的旧资产**：

- `test-execution.zh-CN.md` → 并入 `task/check.md`（用例定义与运行结果必须切开）
- `technical-design-profiles.zh-CN.md` → 降为 `plan` 的 `references/design-profiles.md`，不再独立成模板
- `review-change.zh-CN.md` → 优先作为 `acceptance/` + `task.json` 的人类可读视图，不建第二套台账
- `templates/knowledge/decision.md` → **已删除**（用户确认第一版不设独立 `decisions/`）
- 旧 `prd.zh-CN.md` / `technical-design.zh-CN.md` / `test-cases.zh-CN.md` → **成为安装包默认评审稿模板**（不强制项目使用）

**命名冲突已消解**（2026-10-27）：旧 `prd.zh-CN.md`（人读产品需求书）与 fstar `prd.md`（任务记录）曾同名不同物、存在双权威源风险。现改为**取消 `prd.md` / `design.md` 双轨**——评审稿 `doc/prd.md` 与 `doc/design.md` 是**人机共用的唯一内容源**，不再另存 AI 版。

### 3.5 工具层（④ Tools，2026-10-27 新增）

**fstar 相对 Trellis 的第 5 个自研增量。** Trellis 的工具是写死的（指南直接点名 CodeGraph / QMD / Exa，hook 是固定脚本）；fstar 把「能力」与「工具」拆开，中间用「绑定」连接。

```
能力（capability）      稳定，fstar 定义，跨人不变
   定义 · 判定要点 · 降级路径 · 记录要求
        ↑
绑定（binding）         可变，用户/项目配置，随时可换
   能力 → 实际工具 · 作用域 · 授权状态 · 选择理由
        ↓
实际工具（tool）         外部事实，随时会变
   CLI / MCP server / 宿主 skill / 内置能力
```

**第一版 5 个维度**（`ui-design` 已移出工具层——不属于整体闭环核心要点，定位待后续讨论）：

| id | 能回答什么 | 判定要点 | 默认推荐 |
|---|---|---|---|
| `code-structure` | X 在哪定义 / 谁调用 / 改这影响什么 | 符号级定位；可追溯到文件行；能区分「符号不存在」与「没索引到」 | CodeGraph、LSP |
| `web-research` | 当前版本 / 官方文档 / 上游仓库事实 | 能读到原始来源；能给出版本与出处 | WebSearch、`gh`、Exa MCP |
| `knowledge-retrieval` | 找回项目里以前做过的决定和文档 | 集合新鲜度；关键词与语义两条路线；来源路径可验证 | QMD、项目已有索引 |
| `data-access` | 查 schema、查数据、跑只读 SQL | 只读边界；最小权限；连接与查询真成功 | DBHub、`psql` |
| `test-execution` | 跑起来看结果对不对 | 有可执行命令；结果可复现；失败能定位 | 项目自带 runner |

**分类器三层**（**Python 确定性实现，AI 不进分类路径**）：

| 层 | 做什么 | 不做什么 |
|---|---|---|
| L1 存在性探测 | 清点 PATH 可执行文件 / MCP server / 已装 skill，产出候选清单 | 不做判断 |
| L2 能力特征匹配 | 读工具自述（`--help` / MCP tool 列表 / skill description），与维度**判定要点**匹配 | 不靠名字匹配 |
| L3 绑定与验证 | 生成提案 → 用户确认 → 写 `tools.yaml`；三层验证：可发现 → 客户端加载 → 一次最小真实调用 | 不自动安装 |

**L2 内部三档**（解决「新工具不定时冒出来」）：

| 档 | 做法 | 结论 |
|---|---|---|
| L2a 声明式注册表 | 安装包 `registry/<tool>.yaml` 声明能力映射 | 精确，可 review |
| L2b 维度通用探针 | 能力契约自带探测模式，试未注册工具 | 召回中等，**命中一律标 `weak`** |
| L2c 未分类残渣 | 两档都没命中 → 列候选，用户手动绑一行 | **不引入 AI 兜底** |

升为 `strong` 必须经注册表或用户确认。三层验证大部分可脚本化（「最小真实调用」= 抽一个已知符号 → 跑工具 → 比对 `file:line`）。

**硬边界：fstar 只提议，不装。** 能力缺失 → 说明缺口 + 给出建议来源 + 走契约降级路径。

**存储落点**：

| 路径 | 内容 | 入库 |
|---|---|---|
| `~/.fstar/tools.yaml` | 探测结果 + 能力→工具绑定 | ✅ |
| `~/.fstar/tools.local.yaml` | 本机路径、验证状态 | ❌ |
| `.fstar/tools.yaml` | 项目级覆盖 | ✅ |
| `~/.fstar/runtime/tool-status.json` | 验证结果（事实） | ❌ |
| `~/.fstar/tools/registry.d/*.yaml` | 用户自写的工具注册条目 | ✅ |
| 安装包 `registry/*.yaml` | fstar 维护的已知工具注册表 | ✅ |

优先级：**项目级 > 用户级 > 安装包默认推荐**；注册表同理 **用户 `registry.d/` > 安装包 `registry/`**。

**三个挂钩点**：初始化（`fstar-init` 探测+提案）、hook（`session-context` 检测工具变化并提示，**不自动改绑定**）、skill（`fstar-tools`：查绑定→验证→调用→记录→降级）。

**性能边界**：完整扫描只在 `fstar init` / 显式 `fstar tools scan`；`session-context` 只做 `shutil.which` 存在性检查 + `detected_at` 过期判断；`turn-context` 不碰工具。

详见 `research/tools-capabilities.md`。

### 3.6 目录结构

```text
【安装包】产品默认资源
  hooks/                          平台无关逻辑入口
  adapters/<宿主>/                claude │ codex 的事件·配置·安装适配
  workflows/default.md            阶段与角色路由（条件块表达平台差异）
  skills/fstar-*/SKILL.md         ③ 能力层
  skills/fstar-*/references/      按需参考
  agents/{research,implement,check,editor}.md
  capabilities/<能力>.md          ④ 工具层：能力契约（判定要点+降级路径）
  templates/{doc,entry,task,knowledge,optional}/
  schemas/                        task / context / event / acceptance 格式校验

【用户级】~/.fstar/               跨项目个人内容
  index.md                个人内容索引（条目摘要 + 适用情形 + 路径）
  config.yaml              用户默认配置、工作流版本/来源、平台选择
  .gitignore               忽略 runtime/ 与本机配置
  config.local.yaml        本机路径、可执行文件位置（不入库）
  rules/<主题>.md          明确约束，带范围·来源·原因
  memory/<主题>.md         偏好与经验，非强制
  workflows/<名称>.md      自定义或覆盖流程
  skills/<能力>/           SKILL.md + references/ + scripts/
  capabilities/<能力>.md   覆盖/扩展能力契约
  templates/<产物>.md      自定义模板
  tools.yaml               探测结果 + 能力→工具绑定
  tools.local.yaml         本机路径、验证状态（不入库）
  tools/registry.d/*.yaml  用户自写的工具注册条目
  runtime/projects.json        已知项目 ID ↔ 本机路径
  runtime/sessions/<id>.json   非项目会话定位
  runtime/tool-status.json     能力验证结果（事实，不入库）

【宿主侧】用户级，只装一次，全局可用
  ~/.claude/skills/fstar-*/SKILL.md   13 个 skill（2026-10-27 已定：用户级；含 `fstar-doc`）
  ~/.claude/agents/fstar-*.md         4 个 Agent 角色卡（research / implement / check / editor）
  ~/.claude/commands/fstar/*.md       命令别名（宿主支持时）
  ~/.claude/settings.json             hook 注册（追加，不覆盖用户配置）
  ~/.codex/agents/fstar-*.toml        Codex 侧角色定义

【项目级】<项目>/.fstar/          项目知识与任务
  index.md                项目短背景、入口、规范索引（引用已有 docs）
  config.yaml              稳定项目 ID、配置格式版本、工作流选择
  .schema-version          数据格式版本（决定迁移路径）
  .gitignore / config.local.yaml
  specs/<主题>.md          已确认的项目规范（约束与做法）。按主题归口，可拆目录
  specs/index.md           规范主题索引（标识·适用范围·权威路径·何时读）
  knowledge/               长期知识（事实与历史，不随任务归档消失）
    decisions/             长期决定与原因，时间序，不覆盖
    references/            外部资料快照 + 来源
    context/               领域术语、上下文、常见问题
  tools.yaml               项目级能力绑定覆盖
  tasks/<MM-DD-slug>/
  archive/<年份月份>/<任务目录>/
  runtime/sessions/  runtime/leases/  runtime/reminders.json   ← 不入库

【任务级】tasks/<MM-DD-slug>/      （task.json 内 id 字段为稳定 ID，与目录名解耦）
  task.json          阶段·阻塞·证据[]（含 kind: review）·租约·验收·能力记录·扩展包授权 extensions[]·依赖·交付版本；无顶层 review[]（23 字段）
  doc/               文档目录（人机共用的唯一内容源；启用规划评审包或测试评审包才创建，最小闭环不建）
    prd.md           需求：背景范围·流程·模块条目（稳定 ID）·验收关联·待确认
    design.md           技术方案：边界·接口·取舍·兼容·影响·未覆盖项
    test-cases.md    测试用例：清单表·复杂用例详情·覆盖与待确认
    review-log.md    需求变更/技术方案变更/用例审阅的变更留痕投影（不手改）
  implement.md       执行步骤·验证方式·检查点·回退（仅 AI）
  implement.jsonl    实施时注入的上下文清单（每行 file + reason）
  check.jsonl        检查时注入的上下文清单（每行 file + reason）
  research/<主题>.md
  acceptance/check-<序号>.md       检查报告（人读）
  acceptance/acceptance-<序号>.json 验收记录全文（机器读）
  acceptance/artifacts/
  subtasks/<子任务ID>-<名称>/      子任务同构，不复制父任务背景
```

**最小创建量**：

| 场景 | 文件数 |
|---|---|
| 用户级持久化初始化 | 3（`index.md`、`config.yaml`、`.gitignore`） |
| 正式项目初始化 | 3（`index.md`、`config.yaml`、`.gitignore`） |
| 启用持久任务包 | 1（`task.json`）；同时启用规划评审包则加 `doc/prd.md` |
| 最小闭环（未加载任何包） | **0**（不落盘；用户确认保留在会话内） |

**格式决定依据**：`research/data-formats.md`——Trellis 的 `context.jsonl` / `history.jsonl` 实际不存在（不凭空造）；其 `task.json` 的 `dev_type`/`scope`/`relatedFiles`/`subtasks` 是只写不读的死字段（不继承）；哈希基线随资源走用户级（`~/.fstar/.asset-hashes.json`），项目数据不受更新影响。

### 3.7 核心命令层（⑥ 底座）

| 命令族 | 职责 |
|---|---|
| `task create` / `task state set` | 建任务、转移状态（**唯一合法写入口**；持久任务包启用后） |
| `extension list/enable`（或归入 state 组的等价形态） | 扩展包启用/裁剪记录，写 `task.json.extensions[]` + `events[]` |
| `task archive` | 移动到 `archive/`；**必须在移动前把验收与证据写入 `task.json`** |
| `task lease acquire/release/takeover` | 单写者租约、代次、接管记录 |
| `evidence record/invalidate` | 写 `validates` 指纹、计算 stale |
| `inspect` | 巡检被手改坏的 `task.json`、算出归档缺失项 |
| `reminder snooze/dedupe` | 提醒去重与暂缓 |
| `dispatch`（角色派发 + 变更传导） | 协作层：v1 经宿主原生子 Agent；协议自研 |

> Trellis 正是栽在 `archive` 这一步：它的「完成」由**目录位置**定义（子任务不在 `tasks/` 里就算完成），任何验收与证据模型都必须在 `shutil.move` 之前落盘，移动后 active 指针已被删除。

---

## 四、核心对应关系矩阵

### 4.1 阶段 × 维度矩阵

| 阶段 | 触发 Hook | Agent | Skill | 核心命令 | 模板 | 产物路径 |
|---|---|---|---|---|---|---|
| 接入 | session-context | 主 | `fstar-init` | `project init` | entry/project-index、knowledge/spec | `.fstar/index.md`、`config.yaml`、`.gitignore`、`specs/` |
| `drafting` | turn-context | 主 + research | `fstar-clarify` | `task create` | doc/prd、task/research | `tasks/<id>/doc/prd.md`、`research/` |
| `planned` | turn-context | 主 | `fstar-clarify` 收尾 | `state set planned` | doc/design、task/implement | `doc/design.md`、`implement.md`、`implement.jsonl`、`subtasks/` |
| `implementing` | worker-context | implement | `fstar-execute` | `state set implementing` + 取租约 | — | 代码变更、任务事件 |
| `checking` | worker-context | check 准备/用户审阅 → check 执行 | `fstar-check` | 开发完成后按代码+prd 生成逐条目/场景链用例；用户 approved 且指纹新鲜才可写/运行测试 | doc/test-cases、task/check | `doc/test-cases.md`、测试代码、`acceptance/check-<n>.md` 映射 |
| `fixing` | worker-context | implement | `fstar-check` → `fstar-execute` | `state set fixing` | — | 代码变更、任务事件 |
| `awaiting_acceptance` | turn-context | 主 | `fstar-finish` | `state set awaiting_acceptance`（校验证据新鲜） | — | `acceptance/check-*.md` |
| `done` | — | 主（**仅用户**） | `fstar-finish` | `state set done` | — | `acceptance/acceptance-<n>.json` |
| `archived` | turn-context（巡检） | 主 | `fstar-finish` | `archive`（判据全满足） | — | `archive/<年月>/<任务目录>/` |
| `dropped` | — | 主（**仅用户**） | `fstar-finish` / `fstar-debug` | `state set dropped` | — | 任务事件 |

### 4.2 跨阶段能力落点

| 能力 | 触发 Hook | Agent | Skill | 核心命令 | 模板 | 落盘位置 |
|---|---|---|---|---|---|---|
| 归档提醒 | session-context / turn-context / 显式 continue | 主 | `fstar-continue` | `inspect` + `reminder` | — | `runtime/reminders.json` |
| 知识沉淀 | turn-context（轮末触发候选） | 主 | `fstar-learn` | — | knowledge/rule·memory·spec | `~/.fstar/rules/`、`memory/`、`.fstar/specs/` |
| 回忆 | turn-context | 主 + research | `fstar-recall` | — | — | 只读 |
| 最小闭环 | turn-context | 主（自己执行+检查，不派子 Agent） | 核心 4（`fstar-execute`/`fstar-check`/`fstar-debug`/`fstar-help`） | **不建任务目录、不落盘**；会话内节点路由 | 无 | 会话内；用户确认**保留** |

### 4.3 状态机的三维度与硬拒规则

| 维度 | 含义 | 性质 |
|---|---|---|
| phase 阶段 | 走到哪一步 | 标量、互斥、可推进 |
| evidence 证据 | 支撑当前阶段的产物 | 可失效（指纹变化 → stale） |
| ownership 在途 | 谁在做（会话租约） | 可丢失、可过期（心跳超时 → orphaned） |

`blocked` **不是阶段**，而是阶段上的属性 `{ reason, since }`，解除后回到原阶段。`dropped` 是终态阶段。

**回规划转移（2026-10-26 补）**：`planned / implementing / checking / fixing → drafting`，Agent 发起，必须带回规划原因（需求/设计根本性变更，或 debug 判定根因在需求侧），全部证据标记 `stale`，租约释放。`done` 不重开 `drafting`——重开走 `done → implementing`。这条转移同时是 `fstar-debug`「必要时回规划」和中途需求大变更的合法路径。

**系统必须硬拒**：

- Agent 写 `done` 或 `archived`
- `drafting → implementing`
- `checking → done`
- stale 证据下进 `awaiting_acceptance`
- 用例未获用户 `approved` 或指纹 stale 时让 check 编写/补充测试；仅生成用例即记测试通过
- 容器在子节点未全 `done`/`dropped` 时进 `awaiting_acceptance`

**归档判据**：`phase=done` ∧ 子节点 ∈ {`done`,`dropped`} ∧ 无 stale 证据 ∧ 无未决问题。

**最小闭环与扩展包（2026-10-28 取代旧「轻量 vs 正式」4 条自动升级规则）**：轻量 = 尚未加载扩展包的最小闭环，无二分类判定器。旧 4 条规则（跨会话 / 多文件跨层 / 独立交付物 / 需拆子任务）转化为**扩展信号**，触发主 Agent 协商——按最小闭环接住请求 → 说明收益/代价 → **一次只推荐一个最高价值的包** → 用户同意后加载。默认整包可裁剪、各包授权独立、拒绝后无新事实不重复问。六包见 §一或父任务 `prd.md` §12。

最小闭环**省的是产物和持久化，不是闭环**——三条底线不可裁：实施/检查分离、失败回修复、完成仅用户确认。

---

## 五、一次完整任务的调用时序

```text
用户  │ 启动会话
      ▼
[hook] session-context ──▶ 识别项目、定位当前任务、注入摘要
      ▼
主Agent│ "做 X"  →  调 fstar-clarify
      ├─▶ [research agent] → research/<主题>.md            （需要外部事实时）
      ├─▶ task create → task.json + doc/prd.md
      ├─▶ 复杂度判定 ──▶ doc/design.md / implement.md / subtasks/     （复杂任务）
      └─▶ state set drafting→planned
      ▼
用户  │ "开始"   ← ★ 闸门 1：用户启动确认
      ▼
主Agent│ 调 fstar-execute
      ├─▶ [hook] worker-context ──▶ 按 implement 角色注入上下文
      ├─▶ 派发（宿主原生子 Agent，协议自研；运行时后置）
      │             Claude: stream-json · 真中断  │  Codex: JSON-RPC · turn/steer
      ├─▶ lease acquire（单写者）
      └─▶ state set planned→implementing
      ▼
执行者│ 交付：变更清单 + 自检结果
      ▼
[hook] worker-result ──▶ 存交付引用，安排检查（**≠ 验收**）
      ▼
主Agent│ 进入 checking，派 check 根据已写代码 + prd 生成逐条目/场景链用例草案，或接收用户用例
      ├─▶ 用户审阅 → approved（对话确认可代记原话与指纹）→ 才进入测试编写/执行
      ├─▶ [hook] worker-context ──▶ 注入稳定用例 ID、批准范围、指纹及审批证据
      ├─▶ check 按 ID 写单测、按场景链写集成测试并实际运行；禁止改生产代码
      ├─▶ 失败 F-xxx 可附绑定问题/用例/行号的 unified diff 建议补丁，不自动应用
      ├─▶ acceptance/check-<n>.md：逐用例 ID → 测试代码/标识 → 命令/结果/运行证据
      ├─▶ verdict=fail → state set fixing → 回 implement → 修复 → 回 checking
      └─▶ verdict=pass → state set awaiting_acceptance
             ⚠ 若需求/设计/用例或交付版本指纹已变 → 证据 stale → 有效状态自动落回 checking
      ▼
用户  │ ★ 闸门 2：用户验收确认
      ▼
主Agent│ fstar-finish
      ├─▶ 提交 → 验收记录 acceptance-<n>.json（带可追溯确认来源）
      ├─▶ fstar-learn 候选 → 用户确认 → rules / memory / specs
      ├─▶ archive 判据：done ∧ 子节点∈{done,dropped} ∧ 无stale ∧ 无未决
      └─▶ 整棵目录移入 archive/<年月>/
      ▼
主Agent│ [hook] turn-context 巡检 ──▶ 提醒「还有哪些完成没归档」（可暂缓·去重，不自动归档）
```

---

## 六、覆盖优先级与内容归属

### 6.1 资源覆盖链

```text
用户目录覆盖（~/.fstar/skills|workflows|templates/）
    ▲ 同一相对路径
安装包默认（skills/fstar-*/、workflows/default.md、templates/）
    ▲
项目目录（.fstar/specs/、.fstar/tasks/）   ← 项目级规范优先级高于全局 rules
```

同相对路径的用户模板覆盖安装包模板；未覆盖则回退到安装包默认。

### 6.2 规范优先级（已确认）

| 场景 | 生效内容 |
|---|---|
| 项目有明确规定 | 用项目的，**覆盖**全局对应项 |
| 项目没规定 | 用用户级 `rules/` 补缺 |
| 两者都没说 | 走产品默认行为 |

- 按**事项与适用范围**判断是否覆盖，不因为存在一个项目规范文件就忽略全部全局规则。
- 不回写全局：某个项目的例外不会自动改变其他项目。
- 此优先级只管 fstar 的用户/项目内容，**不改变宿主系统指令、权限限制或用户当前明确指令**。

### 6.3 知识落点

| 内容 | 保存位置 |
|---|---|
| 长期有效的项目规范、决定及其原因 | 项目 `specs/<主题>.md` |
| 当前任务的技术取舍 | 任务 `doc/design.md` |
| 调研过程、候选方案与依据 | 任务 `research/<主题>.md` |
| 跨项目个人规则 | 用户级 `rules/` |
| 个人偏好和经验 | 用户级 `memory/` |
| 已有项目的决策文档 | 仅引用，**不迁移、不删除** |

`rules/` 与 `memory/` 独立：记忆不能自动升级为规则，升级需用户明确确认并保留来源。

---

## 七、缺口归属

| # | 能力 | 归属 | 状态 |
|---|---|---|---|
| 9 | 归档巡检与提醒 | `fstar-continue` | 需补：巡检项清单、去重与暂缓键、提醒文案 |
| 10 | 提交与发布 | `fstar-finish` 内分「提交 → 验收 → 归档」三段 | 不新增技能 |
| 11 | 回滚 | `fstar-execute` 异常路径 | 不单列技能 |
| 12 | 证据失效判定 | **权威归核心命令**（算 + 标）；hook/skill 调同一入口，check 派发/恢复/回收重核用例批准及指纹 | 已定 |
| 13 | 多会话租约接管 | `fstar-continue`（他人活跃租约只读不写；接管记录作废原因与新 owner） | 需显式化 |
| 14 | 产品自身升级 / 迁移 | CLI 更新机制，`fstar-help` 提供说明 | 可延后 |

---

## 八、已知不一致与待修正

### 8.1 文档冲突

`architecture-map.html` 为旧派生预览，已过期，本轮按用户要求不更新。当前命名与用例驱动流程以本 Markdown 和父任务 design.md 为准。

| 项 | 冲突 | 处置 |
|---|---|---|
| skills 数量 | ~~`hooks-skills-templates.md` 列 12 个（含 `fstar-research`）~~ **已同步** | 三份文件均为 **13 个**（新增 `fstar-tools`、`fstar-doc`）；**2026-10-28 起按分层计**：核心 4 自动触发 + 协商路由 8 + 可选 1 |
| 调研能力归属 | 早期把 `trellis-research` 当 skill | 已确认是 Agent 角色，**无同名 skill** |
| 技能常驻成本 | 曾按 338 个技能全量描述估 23k tokens 常驻；又说「预算约 2,720 tokens、超预算描述被丢弃」 | **已按 Claude Code 2.1.311 二进制核实（2026-10-27）**：单位是**字符**不是 token，本机预算 **10,880 字符**；超预算描述**降级为 name-only**（skill 不移除，但自动触发失效）；339 个 skill 的**名字就占 6,247 字符（57%）**。缓解方案见 `research/data-formats.md` §4.1 |

### 8.2 尚未定的技术细节

| 项 | 影响 |
|---|---|
| `task.json.events[]` 的事件粒度与容量上限 | 决定追加式事件数组的字段与裁剪策略 |
| `task.json` 写入的事务一致性 | 决定命令实现形态（写顺序、失败恢复） |
| 验收 JSON 的可核验确认来源 | 验收记录本身不能证明真实用户授权，需宿主输入来源或其他可核验记录 |
| 提醒去重 / 暂缓键的格式 | 决定 `runtime/reminders.json` 的 schema |
| 租约接管记录格式 | 决定 `runtime/leases/<任务ID>.json` 的 schema |
| 版本固定机制 | CLI 包版本 / 已安装资源版本 / 数据格式版本，三者关系待定义 |
| ~~两条派发路径的取舍~~ | ✅ **已定（2026-10-27）：原生优先 + 协议接口**，运行时后置。见 `policy-decisions.md` |
| 旧 `prd.zh-CN.md` 改名 | 避免与 fstar `prd.md` 双权威 |
| **能力维度数量** | 第一版曾列 6 个（含 `ui-design`） | **已定（2026-10-27）：5 个**，`ui-design` 移出工具层，定位待后续讨论 |
| **`context.jsonl` / `history.jsonl`** | 曾在研究文档中被当作既有格式引用 | **已核实：Trellis 里不存在**（`grep` 零命中）。fstar 不采用；上下文清单用 `implement.jsonl` + `check.jsonl`，事件并入 `task.json.events[]`。见 `research/data-formats.md` |
