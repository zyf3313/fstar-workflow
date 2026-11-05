# Hooks、Skills 与模板盘点及 fstar 建议

> **状态（2026-10-29）**：本文件为早期盘点草案，部分内容已被取代。现行权威以父任务 `prd.md` 与 `research/policy-decisions.md` 为准。已被取代的部分：skill 总数 13 → **12**；`fstar-doc` 曾解散、现恢复并收窄为只维护任务 `doc/`；`fstar-finish` 更名 **`fstar-archive`**；`implement.md` 更名 **`plan.md`**（ECC 骨架）；`doc/test-cases.md` 及其模板、测试评审包**暂缓**；`review-log.md` 独立文件**已移除**；`ui-baseline.md`/`ui-feature.md` **暂不保留**；模板候选 16 → **11**；check 不再禁止修改生产代码。其余内容（hooks 分类、安装包与用户/项目目录关系、旧扩展核对）仍有效。

状态：规划草案，未批准实现。范围：本项目安装的 Trellis 0.6.17 相关资源、旧 personal-trellis 扩展指南与模板，以及新版所需资源。不包含用户机器上所有第三方 skills，也不声称已验证所有平台的 hooks。

## 已核对的来源

- `.claude/settings.json:5-70`：3 类注册事件，指向 3 个脚本；SessionStart 注册 startup/clear/compact，PreToolUse 注册 Task/Agent，UserPromptSubmit 注册每轮注入。
- `.claude/hooks/session-start.py:803-899`：阶段摘要、会话定位与规范索引。
- `.claude/hooks/inject-workflow-state.py:209-232`：从 workflow.md 读取状态提示；不是状态转移校验器。
- `.claude/hooks/inject-subagent-context.py:1046-1117`：不同宿主派发事件解析，仅处理相关角色。
- `.trellis/config.yaml:36-51`：任务生命周期回调示例，当前注释未启用；不同于宿主 hooks。
- `.trellis/scripts/hooks/linear_sync.py`：外部 Linear 同步示例，不属于默认启用 hook。
- `.claude/skills/*/SKILL.md`：9 个已安装 Trellis skills。
- `.claude/commands/trellis/{continue,finish-work}.md`：本项目 2 个命令入口；安装包另有 `templates/common/commands/start.md`，为无 SessionStart hook 的平台主动加载上下文，新版可并入 continue 的启动路径。
- `.claude/agents/trellis-{research,implement,check}.md`：3 个原生角色定义；另有 `.trellis/agents/{implement,check}.md` 为 channel worker 角色卡，两个派发路径不能混为一套自动互通的文件。新版建议以统一角色源生成宿主适配，避免两处独立维护。
- `.claude/skills/trellis-meta/references/platform-files/hooks-and-settings.md`：宿主事件与文件位置存在差异，有些平台使用主动读取兜底。
- 旧扩展 10 份指南与 9 份模板详见 `legacy-assets-inventory.md`（独立调研产物）。

## 职责边界

- Hook：宿主在事件发生时执行，做定位、触发和有限上下文注入，不启动耗时调研。
- Skill：告诉 Agent 如何完成一类工作，不直接保证状态转移合法。
- Agent 角色：规定执行者权限、输入和交付，使用相应 skill，避免重复指引。
- 模板：产物骨架，不是执行命令、授权记录或自动触发机制。
- 核心命令：真正校验批准、版本、证据、租约与状态转移；不能仅靠 hook 文本约定。

## Hooks 全量建议

以下内容按**机制类别**分组，不承诺每个平台都有同名事件或单独一个脚本。

### 先厘清：这是四种不同机制，不是一个东西

此前本表把以下五类并列在同一标题下，容易读成「fstar 要提供 7 个 hook」。实际只有 **A / B** 是真正的宿主事件 hook。

| 类 | 名称 | 本质 | 是否内置 | 第一版 | 与 Skill 的关系 |
|---|---|---|---|---|---|
| **A** | 宿主事件 hook | 宿主在固定事件调用固定脚本 | 内置 | ✅ | 工作流环节 → 有对应 skill |
| **B** | 运行时事件 | 协作运行时产出的完成 / 失败 / 取消事件 | 内置 | ✅ | 工作流环节 → 有对应 skill |
| **C** | 核心命令后置回调 | task 命令成功后跑 config 里配的任意 shell | 机制存在 | ❌ 不开放 | 扩展点 → 无 skill |
| **D** | 会话身份解析（非 hook） | 被 hook / CLI / 命令多处调用的解析函数 | 内置基础设施 | ✅ | 基础设施 → 无 skill |
| **E** | 外部集成示例 | Trellis 提供的模板，照抄改可用 | 不提供 | ❌ 不带 | 外部集成 → 无 skill |

### A. 宿主事件 hook（内置，第一版保留）

| 当前资源 / 新职责 | 触发点 | fstar 行为 | 对应 Skill | 绑定方式 | 取舍 |
|---|---|---|---|---|---|
| session-start.py → session-context | SessionStart（startup / clear / compact） | 识别用户/项目入口和当前会话任务；给出摘要与所需规则；没有项目仍能提供全局能力 | fstar-continue | 软触发 | 核心保留，重做两级发现 |
| inject-workflow-state.py → turn-context | UserPromptSubmit（每轮输入） | 刷新阶段、阻塞、待验收/待归档提示；不反复注入整个工作流 | fstar-continue | 软触发 | 核心保留 |
| inject-subagent-context.py → worker-context | PreToolUse Task / Agent（派发前），或 channel 派发包装入口 | 按角色提供任务、适用规则/spec、修订和上下文清单；不注入全部个人记忆。**注入的每个文档必须带版本/指纹** | fstar-execute / fstar-check | **硬绑定** | 核心职责；宿主 hook 按需 |
| **doc-change**（第 5 个） | PostToolUse Edit/Write，命中当前任务 `doc/*.md` | 重算该文件指纹；**不在 `drafting` 阶段**则标相关证据（含评审记录）stale；用例改动即使 drafting 也使已有 review/check evidence stale + 记 `events[]` + 提示需变更传导。**不跑测试、不写报告、不输出噪声** | fstar-doc | 软触发 | 保证「不漏」——绕过 skill 的直接编辑也会被记账。**与下文否掉的「每次文件修改后自动检查」不是同一件事** |

### B. 运行时事件（内置，第一版保留）

| 资源 | 触发点 | fstar 行为 | 对应 Skill | 绑定方式 | 取舍 |
|---|---|---|---|---|---|
| worker-result | 运行时 done / error / killed | 保存交付引用，安排检查或标记待处理；worker done 不等于任务验收 | fstar-check | 软触发 | 核心执行适配职责，不假设宿主 Stop 能完成 |

### C. 核心命令后置回调（机制存在，第一版不开放）

已核实源码：`task_store.py:710`（after_create）、`task.py:254/268`（after_start）、`task.py:292`（after_finish）、`task_store.py:1457`（after_archive）。配置在 `.trellis/config.yaml:36-51`，**默认全部注释掉**。传入 `TASK_JSON_PATH`，失败只打印警告、不阻断主操作。

**这是任意 shell 命令执行入口** —— 宿主 hook 是「宿主在固定事件调固定脚本」，这个是「用户在配置里写命令」。用户已决定第一版不开放自定义 hooks，因此该机制不提供。

### D. 会话身份解析（不是 hook）

`active_task.py:68-121` 的解析链，按优先级依次尝试：

```
TRELLIS_CONTEXT_ID（显式覆盖，hook 传给子进程用）
  → hook payload（宿主传的 session id）
  → 已验证平台环境变量（21 平台审计，其中 12 个无验证名）
  → 30s shell-ticket 桥（AI 无法传环境变量时的兜底）
```

它**依赖** hook（hook 把 `TRELLIS_CONTEXT_ID` 传给子进程），但**本身不是 hook**，是一段被多处调用的解析函数。职责也不同：它解决「我是哪个会话」，这是所有命令的前提，不属于任何单个工作流环节。

### E. 外部集成示例（不提供）

`.trellis/scripts/hooks/linear_sync.py` 的文件头写明 usage（`linear_sync.py:6-9`）：由 `after_*` 回调调用，或手动 `sync`。把任务事件同步到 Linear，依赖外部 `linearis` CLI 与 `.trellis/hooks.local.json`。

Trellis 把它放在 `scripts/hooks/` 目录下，容易误读成「默认启用 hook」。实际定位是**给用户抄的模板**：想接外部系统就照这个写一个放进去，再在 config.yaml 注册。第一版不带。

### 关键：hook 不「对应」skill

正确关系是 **hook 提供判断依据，skill 由 description 触发**，不是硬绑定：

```
Hook（时机） ──注入上下文──▶ 主 Agent ──读到内容──▶ 触发某个 Skill
                                           （靠 description 匹配，不是 hook 写死）
```

例：`session-context` 注入「当前任务 + 阶段」→ 主 Agent 读到 `awaiting_acceptance` → 匹配到 `fstar-finish` 的 description → 调用 `fstar-finish`。

**唯一的例外是 `worker-context`**：它必须按 role 分流（implement 角色注入实现上下文、check 角色注入检查清单），这是硬绑定，因为派发时角色已经确定，不需要靠 description 猜。

所以「hook 是否都对应一个 skill」的答案是：**对应「工作流环节」的有，对应「基础设施 / 扩展点」的没有。**

### 第一版明确不做

| 不做项 | 触发点设想 | 理由 |
|---|---|---|
| 会话结束自动总结/沉淀 | Stop / SessionEnd 等 | 自动全量总结可能制造噪声，退出也不一定可靠触发；由 finish/learn 主动完成 |
| 每次文件修改后自动检查 | PostToolUse 等 | 频繁测试、反复写报告会干扰执行；在实施交付和变更检查点验证。**注意：本条否掉的是「改完就自动跑检查/写报告」，不是 `doc-change`（只做幂等的状态簿记，不跑测试、不写报告、不出噪声）** |
| 自动提交/推送/归档 | 会话结束或 worker done | 容易把技术完成误当作用户授权；按显式授权及任务条件执行 |
| 独立归档提醒 hook | — | 由 session-context、turn-context 和显式 continue/finish 调同一巡检逻辑，复用 `runtime/reminders.json` |
| 任意自定义 shell hook | — | = C 类不开放 |
| 外部 issue 系统同步 | — | = E 类不带 |

归档提醒由同一巡检逻辑收敛，不新增独立提醒 hook。证据有效性在核心阶段转移/读取、check 派发/恢复及结果回收时核查，不依赖文件修改 hook 无遗漏地触发。check 上下文必须包含已批准用例的稳定 ID、范围、版本/指纹和用户审批证据引用；未获用户 approved 或指纹 stale 禁止编写测试。

平台未提供相应 hook 时，由入口 skill 或派发包装器主动加载同样的上下文。具体安装位置按宿主核实，不能把 Trellis 支持的平台数量等同于 channel worker provider 数量。

## Skills：现有九项与新版映射

| Trellis skill | 建议 fstar 归属 | 触发 / 输出 | 取舍 |
|---|---|---|---|
| trellis-brainstorm | fstar-clarify | 需求澄清、范围变化 → PRD，按需设计与执行计划 | 保留，不拆多个重叠规划 skill |
| trellis-before-dev | fstar-execute 的准备步骤 | 开工前 → 读任务、规则、spec，确认变更范围 | 合并，避免独立入口过多 |
| trellis-check | fstar-check | 实施/修复交付 → 检查报告与证据关联 | 保留，不代替用户验收 |
| trellis-break-loop | fstar-debug | 重复失败或复杂问题 → 根因、修复与回归验证建议 | 保留，按需触发 |
| trellis-update-spec | fstar-learn | 列出候选 → 用户确认内容及全局/项目归属 → 项目 specs 或用户 memory/rules | 长期决定及原因写入相关规范，不设独立 decisions/ |
| trellis-spec-bootstrap | fstar-init 的规范整理模式 | 项目接入/已有规范更新 → 实际项目索引与规范 | 合并；不预造空规范 |
| trellis-session-insight | fstar-recall | 回忆旧决策 → 来源与当前结论 | 按需；优先任务/知识文件，历史对话工具为可选依赖 |
| trellis-channel | fstar-execute 的协作参考 | 派发、变更、取消、交付回收 | 保留底层能力，不默认扩展 forum 等非核心功能 |
| trellis-meta | fstar-help | 理解/定制工作流 → 按需架构和配置说明 | 保留为帮助入口 |

### 新版完整建议清单（共 13 个：核心 4 自动触发 + 协商路由 8 + 可选 1；调研是 Agent 不是 skill）

> 修正：`trellis-research` 是 sub-agent type，**不存在同名 skill**。能力发现是调研 Agent 的既有动作，不需独立技能，也不建索引层。
>
> **2026-10-28 skill 分层**：核心 4 个（execute / check / debug / help）自动触发，支撑最小闭环；其余 9 个协商路由——对应扩展包获用户同意后由主 Agent 显式调用，配 `skillOverrides` 降 listing 占用。扩展协商本身不加第 14 个 skill，由主 Agent 按短路由规则处理（SessionStart 注入）。
>
> 轻重形态（2026-10-28 定案）：轻量 = 尚未加载扩展包的最小闭环，无轻量/正式二分类判定器；六包协商见父任务 `prd.md` §12。

| Skill | 分层 | 主文件与按需参考 | 输入 → 输出 |
|---|---|---|---|
| fstar-init | 协商（项目治理包） | SKILL.md；references/onboarding.md、spec-bootstrap.md | 项目接入意图 → 最小目录与已有文档引用 |
| fstar-clarify | 协商（规划评审包） | SKILL.md；references/clarification.md、design-profiles.md | 用户需求 → PRD/按需 design/implement |
| fstar-execute | **核心（自动触发）** | SKILL.md；references/before-dev.md、dispatch.md、changes.md、capability-discovery.md | 已批准任务 → 派发、变更传导、实施交付 |
| fstar-check | **核心（自动触发）** | SKILL.md；references/testing.md、document-consistency.md | 开发完成后据已写代码 + prd 生成逐条目/场景链用例（或接收用户用例）→ 用户 `approved` 且指纹新鲜 → 按稳定 ID 写单测/集成测试并运行 → 证据映射；失败可附不自动应用的建议补丁 |
| fstar-continue | 协商（持久任务包） | SKILL.md | 会话任务和执行状态 → 下一步，不重复派发 |
| fstar-finish | 协商（持久任务包） | SKILL.md；references/acceptance-archive.md | 检查结果 → 用户验收、沉淀检查、归档提议与授权后执行 |
| fstar-debug | **核心（自动触发）** | SKILL.md；references/root-cause.md | 失败证据 → 定位与验证，必要时回规划 |
| fstar-learn | 协商（项目治理包） | SKILL.md；references/knowledge-routing.md | 候选经验 → 分类沉淀、来源及索引更新 |
| fstar-recall | 协商 | SKILL.md；references/history-sources.md | 回忆问题 → 相关记录与出处 |
| fstar-help | **核心（自动触发）** | SKILL.md；references/layout.md、configuration.md | 使用/定制问题 → 定位与说明 |
| fstar-tools | 协商（工具能力包） | SKILL.md；references/contracts.md、probe.md、bindings.md | 能力维度 → 查绑定 → 验证 → 调用 → 记录 → 缺口走降级 |
| fstar-doc | 协商（规划评审/测试评审包） | SKILL.md；references/doc-consistency.md | 定点修改要求 → 派 editor → 回读校验 → 指纹/stale 更新 → 传导 → 改了哪几处的摘要 |
| fstar-ui-design（可选） | 协商 | SKILL.md；references/ui-design.md | 实际 UI 需求 → UI 基线/功能设计 |

核心 4 个 + 协商 9 个（含可选 UI）共 13 个；另有 4 个 Agent 角色（research / implement / check / **editor**），不是 skill。命令别名如 /fstar:continue、/fstar:finish 仅在宿主支持时提供，不另写一份流程。主 Agent 负责协调，四个基础执行角色按需使用（多 Agent 包启用前主 Agent 自己干）。

**`fstar-tools` 的硬边界**：不自动安装任何工具；不自动改绑定；不替代 `fstar-check` 的验收判断。详见 `research/tools-capabilities.md`。

## 模板建议清单

只有发生相应活动才生成产物。小任务不要求全套文档。

| 模板路径（安装包内） | 实际产物位置 | 核心内容 / 时机 |
|---|---|---|
| templates/doc/prd.md | tasks/<任务>/doc/prd.md | 评审稿·需求：背景范围·流程·模块条目（稳定 ID）·验收关联·待确认；人机共用 |
| templates/doc/design.md | tasks/<任务>/doc/design.md | 评审稿·技术方案：边界·接口·取舍·兼容·影响·未覆盖项；人机共用 |
| templates/doc/test-cases.md | tasks/<任务>/doc/test-cases.md | 开发完成进入 checking 后，check 据已写代码 + prd 生成逐条目用例与场景链用例，或接收用户提供/修改；approved 且新鲜才驱动测试代码；生成不等于通过 |
| templates/doc/review-log.md | tasks/<任务>/doc/review-log.md | 需求变更 / 技术方案变更 / 用例审阅三类事件的变更留痕投影（源自 events[] / evidence[]，不手改） |
| templates/task/implement.md | tasks/<任务>/implement.md | 顺序、检查点、验证与回退；复杂任务（仅 AI） |
| templates/task/research.md | tasks/<任务>/research/<主题>.md | 问题、来源、发现、限制；实际调研 |
| templates/task/check.md | tasks/<任务>/acceptance/check-<轮次>.md | 逐条稳定用例 ID → 测试代码路径/测试标识 → 实际运行命令、结果与证据；含交付/用例版本及指纹、环境、run id、未运行/通过/失败/阻塞/跳过；每轮检查 |
| templates/knowledge/rule.md | ~/.fstar/rules/<主题>.md | 要求、范围、原因、确认来源 |
| templates/knowledge/memory.md | ~/.fstar/memory/<主题>.md | 偏好/经验、场景、来源；非强制规则 |
| templates/knowledge/spec.md | .fstar/specs/<主题>.md 或已有规范 | 项目约束、例子、验证方法 |
| templates/entry/user-index.md | ~/.fstar/index.md | 用户规则/记忆/定制资源索引 |
| templates/entry/project-index.md | .fstar/index.md | 项目简短背景、文档和规范索引 |
| templates/optional/exploration.md | tasks/<任务>/research/exploration.md | 参考项目探索或重要选型的证据与取舍，简单事实查询不生成 |
| templates/optional/review-change.md | tasks/<任务>/research/change-<序号>.md | 重要范围变更与影响；小修订只记 history |
| templates/optional/ui-baseline.md | 已有设计目录或 .fstar/specs/ui-baseline.md | 项目视觉与交互基线，不反复随任务复制 |
| templates/optional/ui-feature.md | tasks/<任务>/design/ui-feature.md | 功能页面、状态和交互设计 |

技术设计 profiles 应作为 fstar-clarify 的 references/design-profiles.md，按项目类型选章节，不再作为独立产物。test-execution 与 check 合并为一份实际检查报告；复杂用例执行表可放附录或附件。

结构化记录使用 schema/程序生成，不允许 Agent 把模板占位符当成有效批准：task.schema.json、context.schema.json、event.schema.json、acceptance.schema.json。配置默认值由程序维护；config.yaml 只写需要的配置，不再提供重复的手工状态模板。

## 旧扩展核对后的补充

旧库 10 指南和 9 模板已逐项盘点，见 legacy-assets-inventory.md。以下为汇总建议：

- module-clarification、product-technical-design → plan 的澄清/设计参考；不另起一套与任务 PRD 平行的需求权威文档。大型产品文档可由任务引用，明确单一权威来源。
- code-search、web-research、knowledge-search → research/recall 的按需参考。
- document-consistency、testing-acceptance → check 的核心参考，需求变更时 execute/plan 也引用同一份。
- code-comments → execute 的编码参考；不未经确认升级为用户硬规则。
- database-access → execute/research 共享的数据库访问参考，按需启用，不单列数据库 skill。
- ui-design → 可选 UI skill 与两份模板。
- 5 篇指南重复的能力发现/安装约定抽为安装包 references/capability-discovery.md；技能按需引用。发现工具缺失不等于有权自动安装。
- 旧 prd/technical-design 的详细章节按复杂度整合入 `doc/prd.md` 与 `doc/design.md`，不另建同义产物；profiles 放 plan 的设计参考。**2026-10-27 更新：取消「AI 版 prd/design」双轨——评审稿是人机共用的唯一内容源，旧 zh-CN 三份模板成为安装包默认评审稿模板。**
- test-cases 是用例定义（评审稿 `doc/test-cases.md`），check 是运行结果（`acceptance/check-<轮次>.md`），二者不能混成一份含糊记录。check 仅可在已确认用例范围内写测试代码，禁止改生产代码；生产缺陷交 fixing/implement。用户改用例使对应 review/check evidence stale；即使 drafting 也不能保留旧批准为有效，历史仍保留。
- review-change 优先引用 events/acceptance 或作为方案附录；只有较大范围变更才生成独立报告，不维护第二套状态台账。
- 带日期的工具测试数据和外部候选仓库留作研究资料，不能当永久规范。
- 旧模板为中文。**2026-10-27 已定：模板由用户拥有、可替换**——章节、布局、语言、图示、条目 ID 写法全归用户；fstar 只留语义槽位（`artifact_type`/`version`/`review_state`/`author`/`date`/`reviewer` + 稳定条目 ID + 关联），自定义模板通过 `templates/<name>.mapping.yaml` 对接；解析优先级「任务显式指定 > 项目模板 > 用户模板 > 安装包默认」；提取不到的槽位明确提示、不推断。

## 第一版 Hooks 范围（已确认）

用户确认：**第一版不开放自定义 hooks**。内置 hooks 随产品提供并按宿主注册；用户与项目目录不提供任意脚本执行入口。需要接入通知、外部系统时再评估。

## 外部第三方 Skills：事实与定位建议

### 已核对的事实

- 旧扩展仓库 `personal-trellis` **没有** curated skills 目录；`.claude/skills/` 只是 Trellis 生成的 9 个内置技能。其自有资产是 10 份指南 + 9 份模板（见 legacy-assets-inventory.md）。
- README 中提到的第三方来源为 Emil Skills、DBHub 等，是「按需发现与安装」的目标，不是已收编内容。
- 用户机器 `~/.claude/skills/` 现有 **339 个真实目录**（非符号链接），来自 marketplace（`claude-plugins-official` 23M、`omc` 45M），覆盖生信、数据科学、AIOS 角色、分析等大量领域。
- 这些技能由宿主自行发现与自动触发，不在项目仓库内，也不受 fstar 管理。

### 定位建议

**不建议把第三方技能收编进 fstar 安装包。** 理由：

1. 宿主已经能发现它们；再复制一份会产生同义技能竞争触发、版本漂移和维护负担。
2. 许可与来源各异，收编需要逐个评估。
3. 339 个技能说明真正的痛点是**找不到、不知道该用哪个**，而不是数量不足。

**建议把第三方技能当作「外部能力来源」，只引用不复制**，并新增一层能力发现：

| 层 | 职责 |
|---|---|
| 外部技能（宿主自有） | 具体领域能力，fstar 不管理其内容 |
| fstar 能力发现 | 按当前任务意图检索可用技能、判断是否匹配、记录用了哪个 |
| fstar 核心技能 | 工作流阶段本身（plan/execute/check 等），不依赖外部技能存在 |

能力发现的基本行为：扫描宿主的技能根目录与已装 marketplace → 按名称/描述匹配当前任务意图 → 展示候选与来源，由用户或主 Agent 选择 → 在任务上下文清单或检查报告中记录实际使用的能力及版本/来源。不允许自动安装。

这与旧指南中重复出现的「能力发现与软安装」样板（5 篇指南各写一遍）是同一件事，应合并为**一份共享参考 + 一个 fstar 技能入口**，而不是散落在各阶段技能里。

### 与「find-skills」类能力的差异

单纯列出技能不够，还需要：与任务意图的匹配、使用记录、以及「没有合适能力时说明缺口」而不是硬凑。这部分属于 fstar 的增值点，适合放在 research/execute 的前置步骤。

## 安装包、用户目录、项目目录的关系

```text
<产品安装包>/
  hooks/                         # 平台无关逻辑的入口，具体语言待定
  adapters/<宿主>/               # 事件、配置、skill/agent 安装适配
  workflows/default.md          # 阶段与角色路由，引用 skills
  skills/fstar-*/SKILL.md        # 上述入口
  skills/fstar-*/references/     # 按需参考
  agents/{research,implement,check,editor}.md
  templates/{doc,entry,task,knowledge,optional}/
  schemas/                      # 状态与证据格式校验

~/.fstar/
  rules/  memory/               # 用户内容，已确认分开
  skills/ workflows/ templates/ # 用户定制，按需

<项目>/.fstar/
  specs/ tasks/ archive/            # 项目知识与任务产物；决定的原因写入相关规范
```

此处为发布资源的职责布局，不决定源代码语言或 monorepo 结构。平台 skill 目录通常不能自动发现 ~/.fstar/skills；安装器必须按宿主支持生成/关联入口，更新时只管理自身文件。用户模板覆盖使用相同相对路径，默认回退到安装包模板；覆盖优先级仍待最终评审。

不新增 ~/.fstar/hooks/ 或项目 hooks/ 作为默认任意脚本执行入口。内置 hook 实现随安装包更新，实际注册保存在宿主要求的配置位置。新增自定义 hook 系统为独立范围，不由本轮盘点默认引入。

## 待确认与已知边界

- 本轮新增目录与 skill 名称为建议，不是已批准规格。
- 规则与项目规范的冲突策略仍未决，不因本轮盘点推定用户答案。
- 以前把 CLIAdapter 平台列表当作 channel worker 支持范围的说法不可靠；多平台安装、原生子 Agent 与 channel provider 必须分别核对。
- 旧扩展具体迁移建议以独立盘点为依据；保留指南功能不等于每份都注册一个 skill。
- 默认建议核心 hooks 随产品提供，先不开放用户任意脚本 hooks，以减少配置和维护面；用户可能需要自定义接入，此项待评审。
