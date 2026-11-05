# 数据格式逐项梳理：Trellis → fstar

状态：规划草案，2026-10-27。**不构成实现授权。**

> **现行口径（2026-10-29）**：文中 `doc/test-cases.md` 与 `doc/review-log.md` 已不再保留（前者暂缓、后者移除）；`implement.md` 已更名 **`plan.md`**；`knowledge/` 仅 `context/` 与 `references/`（无 `decisions/`、无 `history.md`）；状态机为 3 态、归档为命令；rule/memory/spec 统一 `fstar.knowledge.v1`，`specs/` 默认英文。其余格式决定（task.json 字段、jsonl 取舍、归档布局、config 字段、版本与哈希）仍有效。

用户 2026-10-27 拍板：**fstar 完全自研，Trellis 只作为参考项**。本文档把 Trellis 的每一种数据格式逐个过一遍，逐条给出 fstar 的决定与理由。

---

## 零、原则

| 原则 | 含义 |
|---|---|
| **不复制源码** | 不 fork、不粘贴 Trellis 的 Python/JS 实现。AGPL-3.0 不传染，fstar 可独立分发 |
| **不复制格式** | 数据结构由 fstar 的设计重新推导，不做「逐字节对齐」 |
| **Trellis 只作参考** | 它的抽象、踩过的坑、已验证的交互形态可借鉴；它的字段和实现不继承 |
| **沿用要有理由** | 下列「沿用」项不是因为「Trellis 有所以照抄」，而是因为该形状已被验证、且 fstar 的需求没有推翻它 |

**审计方法**：`task.py` 的 `cmd_create`（`task_store.py:329-560`）写什么字段、`types.py:20-52` 声明什么 schema、`.trellis/.template-hashes.json` 记录什么、`cmd_archive`（`task_store.py:1257+`）移动什么。**以写盘路径为准，不以文档为准**——文档与实现有漂移（见 §五）。

---

## 一、A 组：项目级控制与状态

| Trellis 格式 | fstar 决定 | 理由 |
|---|---|---|
| `.trellis/config.yaml` | `.fstar/config.yaml`，**字段重设计** | 见 §1.1 |
| `.trellis/.gitignore` | `.fstar/.gitignore`，规则重写 | fstar 新增 `runtime/`、`tools.local.yaml`、`identity`；`knowledge/` 是否入库由用户选 |
| `.trellis/.version`（`0.6.17`） | `~/.fstar/version`（安装包版本，用户级）+ `.fstar/.schema-version`（**数据格式版本**，项目级） | Trellis 的 `.version` 记的是脚本版本，而 fstar 的脚本在安装包里、不在项目里。项目级真正需要记的是**数据格式版本**——它决定迁移路径 |
| `.trellis/.template-hashes.json` | `~/.fstar/.asset-hashes.json`（**用户级**） | **关键改进**：fstar 的资源（skills/templates/capabilities/agents）在安装包和用户级目录，**不在项目里**。哈希基线跟着资源走。项目级数据是用户自己的产物，更新不该碰 |
| `.trellis/.developer`（`name=`, `initialized_at=`） | `~/.fstar/.identity`（用户级单份） | fstar 是个人系统，身份不需要按项目区分 |
| `.trellis/.runtime/`（sessions/*.json、update-check-*.marker） | `~/.fstar/runtime/` | 会话状态、更新检查标记、工具验证状态都在用户级 |
| `.trellis/workflow.md`（39KB） | `~/.fstar/workflow.md`（用户级单一来源）+ 项目级 `workflow.local.md` 覆盖片段 | Trellis 每项目一份 39KB 是重复负担。fstar 全局一份 + 按需覆盖。**且要瘦身**：39KB 是因为塞了大量说明文字，应拆成「流程编排」+「skill 按需加载」 |

### 1.1 `config.yaml` 字段级决定

| Trellis 字段 | fstar | 理由 |
|---|---|---|
| `session_commit_message` | 改名 `journal_commit_message` | 语义更准 |
| `max_journal_lines` | 沿用 | |
| `session_auto_commit` | **改为 `auto_commit`，默认 `false`** | 见 §六待定 3 |
| `hooks.after_create/start/finish/archive` | **删除** | 第一版**不开放自定义 hooks**（已定）。这四个 shell 回调正是 Trellis 的「C 类核心命令后置回调」，fstar 第一版不提供 |
| `packages` / `default_package` | **第一版删除** | monorepo 支持。保留扩展位 |
| `channel.worker_guard`（idle_timeout / max_live_workers） | **删除** | fstar 用宿主原生子 Agent，worker 预算由宿主管，不需要自己的 guard |
| `codex.dispatch_mode` | 改为 fstar 自己的 `dispatch.mode` | 保留「auto / inline」思路 |
| `context_injection`（max_file_bytes / max_artifact_bytes / max_total_bytes） | **沿用，字段名不变** | 这是个好设计：限制注入体积，超了降级成索引行。直接继承形状 |
| `prompt_injection.skip_keyword` | 沿用，默认 `no-fstar` | |
| — | **新增** `tools`（分类器扫描策略）、`knowledge`（知识库沉淀范围）、`evidence`（指纹策略） | 对应 fstar 新增的三层 |

---

## 二、B 组：任务数据

| Trellis 格式 | fstar 决定 | 理由 |
|---|---|---|
| `tasks/<MM-DD-slug>/task.json` | **重造**，字段表见 §2.1（23 字段） | 核心数据结构，**持久任务包启用后才创建**。Trellis 是 3 状态，fstar 是 7 阶段 + 证据 + 租约 + 验收 + 评审 + 扩展授权 |
| `tasks/<MM-DD-slug>/prd.md` | **不采用，改评审稿**（2026-10-27） | 与 `design.md` 一并被 `doc/prd.md` / `doc/design.md` 取代。理由：用户要「人机共用的唯一内容源」，双轨必然漂移。任务契约（范围、AC、未决问题）写进评审稿正文 |
| `tasks/<MM-DD-slug>/design.md` | **不采用，改评审稿**（2026-10-27） | 被 `doc/design.md`（评审稿·技术方案）取代。任务级技术设计与「给人评审的技术方案」是同一份东西 |
| （fstar 自创）`tasks/<MM-DD-slug>/doc/` | **新目录** | 文档四件：`prd.md` / `design.md` / `test-cases.md` / `review-log.md`。**人机共用正文**；必填语义槽位见父任务 `design.md` §4.2。`review-log.md` 是需求变更 / 技术方案变更 / 用例审阅三类事件的变更留痕投影，不手改。**启用规划评审包或测试评审包才创建**（2026-10-28 更新；此前「正式任务才有」已随轻量/正式二分类取消）；最小闭环不落盘 |
| `tasks/<MM-DD-slug>/implement.md` | **沿用 + 增要求** | 增「前置依赖」「验证命令」「回滚点」。**仅 AI 侧**——用户不读执行计划 |
| `tasks/<MM-DD-slug>/implement.jsonl` | **沿用格式** | 每行 `{"file": "<path>", "reason": "<why>"}`，只放 spec/research 文档，不放代码路径 |
| `tasks/<MM-DD-slug>/check.jsonl` | **沿用格式** | 注入场景就是「实施」和「检查」两个，**不引入第三个**。fstar 阶段虽多，但需要注入上下文的只有这两处 |
| （fstar 自创）`context.jsonl` | **不采用** | 原设计想用一个按 role 列出上下文清单的文件。审计后拆回 Trellis 已验证的**两个**文件——注入场景本来就只有实施与检查两处，一个文件反而要再加 role 字段 |
| （fstar 自创）`history.jsonl` | **不采用，职责拆散** | 它的三个职责各有更合适的落点，见下 |
| `tasks/<MM-DD-slug>/research/` | **沿用** | 调研产物目录。**仅 AI 侧** |
| `tasks/<MM-DD-slug>/acceptance/` | **沿用 + 明确职责** | `check-<n>.md` 记录稳定用例 ID → 测试代码路径/测试标识 → 实际运行命令/结果/证据引用，并带交付版本、用例版本/指纹、环境、run id 与逐用例状态。**用例定义在 `doc/test-cases.md`，运行报告在这里**——定义与执行分离（沿用 `test-cases.zh-CN.md:56`） |
| `tasks/<MM-DD-slug>/subtasks/` | **沿用嵌套** | 已定：主任务内含子任务，目录直接体现归属 |
| `tasks/archive/<YYYY-MM>/<dir_name>/` | **沿用** | 按月归档，整棵移入。Trellis 的 `archive_destination_for` 逻辑（`task_store.py:1257+`）在归档前检查目标冲突，fstar 保留这个防护 |

用例文件的生成不产生通过证据。用户修改用例后，对应 review/check evidence 按稳定 ID 及依赖关系 stale（即使处于 drafting 且已有证据）；恢复执行和回收旧结果时重查指纹。测试代码及运行所用交付版本也属于检查证据覆盖范围，详细算法留给 core-commands。

命名轨迹：此前曾选 `TDD.md`，现撤回为 `doc/design.md`；四件套见上表。

### 2.2 `history.jsonl` 的三个职责去哪

原设计里 `history.jsonl` 承担三件事。拆开看，每件都有更合适的落点：

| 原职责 | fstar 落点 | 理由 |
|---|---|---|
| 阶段变化 | `task.json.events[]`（追加式事件数组） | 任务内事件有界（几十条量级），放 JSON 里即可；不需要单独的追加文件，也就没有「两个文件的一致性」问题 |
| 需求变更 | `task.json` 的文档修订字段 + `doc/design.md` 的修订章节 | 变更**正文**是人读的长文本，塞进 JSON 事件不合理。JSON 只记「什么时候改的、改了哪份文档的哪一版」 |
| 批准与验收记录引用 | `task.json.acceptance` + `acceptance/acceptance-<n>.json` | 验收闸门需要可验证的确认来源，独立成结构才有意义 |

**收益**：不再需要保证「`history.jsonl` 与 `task.json` 的事务一致性」——两个文件写同一个事实的经典难题直接消失。命令只写 `task.json` 一个文件。


### 2.1 `task.json` 字段级决定

Trellis 有 26 个字段（`types.py:20-52`）。

| Trellis 字段 | fstar | 理由 |
|---|---|---|
| `id` / `name` / `title` / `description` | 沿用 | |
| `status`（`planning`/`in_progress`/`completed`） | **`phase`**（`drafting`/`planned`/`implementing`/`checking`/`awaiting_acceptance`/`done`/`archived`）+ **`blocked`**（布尔属性） | 核心差异。`blocked` 是属性不是阶段 |
| — | **新增 `evidence[]`** | 每条：`kind` / `validates`（需求/设计/用例指纹及交付版本）/ `state`(`valid`\|`stale`) / `produced_at` / `producer`。评审记录也只存这里：`kind: review`，另含 `verdict` / `by` / `at` / `notes` / `source`，绑定稳定条目 ID；**不设顶层 `review[]`** |
| — | **新增 `lease`** | `holder` / `acquired_at` / `expires_at` / `takeovers[]` |
| — | **新增 `acceptance`** | `confirmed_at` / `confirmed_by` / `source`（**可验证的确认来源**）/ `evidence_refs[]` |
| — | **不新增顶层 `review[]`**（2026-10-28 简化） | 2026-10-27 曾拟新增该字段，现合并进 `evidence[]`。prd/design 批准由 `planned → implementing` 启动确认 + 当时指纹记录；唯一必须单独落评审证据的是用例批准。check 写测试前必须验证当前用例有可核验用户 `approved`；用户供稿不等于批准，同事意见不能代替用户批准 |
| `completedAt` | **拆成 `doneAt` + `archivedAt`** | Trellis 把「完成」和「归档」压成一个状态。fstar 是两个阶段，时间要分开 |
| `children` | 沿用 | 子目录名列表 |
| `subtasks` | **删除** | 与 `children` 语义重叠，全仓库无消费方 |
| `dev_type` | **删除** | **只写不读**（`task_store.py:534` 写入 `None`，无任何读取方）→ 死字段 |
| `scope` | **删除** | 有 `cmd_set_scope` 写入（`task_store.py:1877`），无消费方 → 死字段 |
| `relatedFiles` | **删除** | **只写不读** → 死字段。fstar 用 `evidence[]` + `capabilities[]` 替代，语义更强 |
| `priority`（P0–P3） | 沿用 | |
| `creator` / `assignee` | 沿用，单用户下取值相同 | 保留 `creator` 做溯源 |
| `createdAt` | 沿用 | |
| `branch` / `base_branch` / `worktree_path` / `commit` / `pr_url` | 沿用 | git 集成确实有用 |
| `package` | **第一版删除** | monorepo，后置 |
| `notes` / `meta` | 沿用 | `meta` 是自由扩展位，很好用 |
| — | **新增 `capabilities[]`** | 本任务用过哪些能力维度 + 实际工具 + 版本（provenance 记录） |
| — | **新增 `extensions[]`**（2026-10-28，最小内核+扩展包定案） | 扩展包授权记录，每条：`id` / `enabled_at` / `source` / `scope: full\|custom` / `included[]` / `excluded[]` / `reason`。**与 `capabilities[]` 分离、不得混写**（扩展授权是用户决策，capabilities 是工具 provenance）；启用/裁剪/停用历史走 `events[]`。未启用持久任务包时授权只存会话上下文 |

**净效果**：字段数 26 → **23**（2026-10-28 将曾拟新增的顶层 `review[]` 合并进 `evidence[]` 后为 22；同日新增 `extensions[]` 至 23——**注意这两次 23 不是同一回事，前者已撤回**），但**语义密度显著提高**（4 个死字段换成证据/租约/验收/能力/扩展授权五个真正被读写的结构）。

---

## 三、C 组：规范与知识

| Trellis 格式 | fstar 决定 | 理由 |
|---|---|---|
| `.trellis/spec/<package>/index.md` + 各主题 md | `.fstar/specs/<主题>.md` + `.fstar/specs/index.md` | **不按 package 分**：fstar 是个人跨项目系统，package 概念弱。Trellis 的索引三段式（Purpose / 可用清单 / 何时读）形态**可借鉴** |
| `.trellis/agents/<role>.md`（frontmatter：`name`/`description`/`provider`/`labels`） | `~/.fstar/agents/<role>.md`（用户级） | fstar 自带的角色卡，不是项目内容。项目可覆盖 |
| `.trellis/.claude/`、`.codex/` 之外的宿主配置 | 见 §四 | |
| — | **新增 `.fstar/knowledge/{decisions,references,context}/`** | 已定（`research/knowledge-base.md`） |

**Trellis 的 spec 三层索引值得借鉴的细节**：每个 `spec/<pkg>/index.md` 开头有 `Purpose`，中间有「可用清单」表格，末尾有「何时该读」的触发条件清单。这解决了「Agent 只读必要上下文」——**触发条件比清单更重要**。fstar 的 `specs/index.md` 应保留这个结构。

---

## 四、D 组：工作记录与宿主侧

| Trellis 格式 | fstar 决定 | 理由 |
|---|---|---|
| `.trellis/workspace/index.md`（全局开发者索引） | **不采用** | 单用户系统不需要「所有开发者的总索引」 |
| `.trellis/workspace/<dev>/index.md` | **不采用** | 同上 |
| `.trellis/workspace/<dev>/journal-N.md`（2000 行轮转） | **不采用** | 与 `directory-proposal.md` 的删减建议一致——「不新增 journal/、workspace/」。任务历史由 `task.json` 的 `events[]` + `acceptance/` 覆盖，跨任务回忆由 `knowledge/` + `fstar-recall` 覆盖。最小闭环有意不持久化 |
| `.trellis/workspace/<dev>/tasks/*.json` + `archive/` | **不采用** | **实际不存在**（`paths.py` 无对应路径）——文档漂移。且与 `tasks/` 职责重复 |
| `.claude/skills/trellis-*/SKILL.md` | **`~/.claude/skills/fstar-*/`（用户级）** | **已确认（2026-10-27 用户决定）**：用户级，全局可用。代价与缓解见 §4.1 |
| `.claude/agents/trellis-*.md` | `~/.claude/agents/fstar-*.md`（用户级） | 同上 |
| `.claude/commands/trellis/*.md` | `~/.claude/commands/fstar/*.md`（用户级） | 命令别名，宿主不支持时省略 |
| `.claude/settings.json` | **追加** hook 注册，**绝不覆盖**用户已有配置 | Trellis 的 `.template-hashes.json` 里记了它，说明它也在被模板管理——但 fstar 不该覆盖用户的 settings |
| `.codex/agents/trellis-*.toml` | `~/.codex/agents/fstar-*.toml`（用户级） | |
| `.trellis/hooks/linear_sync.py` | **不提供** | 外部集成示例，不在第一版范围 |

### 4.1 宿主资源装用户级：代价与缓解（已确认）

**决定**：fstar 的 13 个 skill、4 个 Agent 角色卡、命令别名、hook 注册**全部装用户级**，装一次全局可用。

**为什么是用户级**：fstar 的定位是「个人跨项目工作流系统」。用户级安装意味着——

- 任意目录都能触发 fstar 流程，不必先 `fstar init`；
- 最小闭环（「处理小事不需要初始化项目工作流」）天然成立，因为 fstar 的能力本来就在全局；
- 项目级只留**数据**（`config.yaml` / `specs/` / `knowledge/` / `tasks/`），不装程序。

**代价（已接受的风险）**：Claude Code 的 skill listing 有预算上限，超预算的 skill 描述会被降级，**自动触发随之失效**。用户已有 339 个 skill，fstar 再加 13 个会加剧拥挤。

#### 4.1.1 已核实的宿主机制（Claude Code 2.1.311，实测 + 二进制内嵌 schema）

> 以下事实由 `claude-code-guide` 在安装的二进制 `~/.nvm/.../@anthropic-ai/claude-code/bin/claude.exe`（2.1.311）中核实，含内嵌 schema 原文与实测数据。

| 机制 | 事实 |
|---|---|
| **`skillListingBudgetFraction`** | 真实设置项，默认 `0.01`（1%）。**单位是字符不是 token**：`预算字符数 = 上下文 token 数 × 每 token 字节数 × fraction`。每 token 字节数取自模型注册表，**回退值 4** |
| **本机实际预算** | 用户 `~/.claude/settings.json` 有 `env.CLAUDE_CODE_MAX_CONTEXT_TOKENS = 272000` → `272000 × 4 × 0.01 =` **10,880 字符**。若模型别名未被识别、上下文回退 200k，则为 8,000 字符 |
| **超预算的后果** | 描述被**降级为 name-only**（清单里只剩 `- skill-name`），**skill 本身不会被移除**。但模型没有描述可匹配 → **自动触发失效**。另有日志：`Skill listing over budget: N skills, D chars > B budget` |
| **预算分配算法** | ① 每条描述先过单条上限 `skillListingMaxDescChars`（默认 1536，超出截断）；② 总额够则全给；③ **内置 skill 永远保留完整描述**；④ 其余按**使用优先级分数**贪心分配：`usageCount × max(0.5^(距上次使用天数/7), 0.1)`（7 天半衰期，下限 0.1×）；⑤ 平局按清单位置——**不可靠** |
| **致命细节** | **从未被调用过的 skill 分数为 0，平局全输**。fstar 的 13 个新 skill 会第一批被降级 |
| **`skillOverrides`** | 真实设置项，取值 `on` / `name-only` / `user-invocable-only` / `off`。**按 skill 名精确匹配，无通配符**。可写在用户级、项目级、local 三处 settings；同 key 项目级优先。`user-invocable-only` 与 `off` **完全不进模型清单，消耗 0 字符** |
| **`disable-model-invocation`** | SKILL.md frontmatter 布尔字段。为 true 时模型不能调用、只能用户打 `/name`，且**不进清单，消耗 0 字符**。注意与 `user-invocable: false`（反向）区分 |
| **按项目过滤** | **不存在按项目「包含」用户级 skill 的机制**。唯一的按项目手段是用 `skillOverrides` 做**排除**（写进该项目的 `.claude/settings.local.json`），且必须逐个列名 |
| **使用数据位置** | `~/.claude.json` 顶层 `skillUsage`，结构 `{ "<skill 名>": { usageCount, lastUsedAt } }` |
| **`/skills` 写哪** | 写 `.claude/settings.local.json`（项目级 local）。**用户全局的 override 需手工写进 `~/.claude/settings.json`** |
| **插件 skill** | 官方文档与二进制一致：`skillOverrides` **不影响插件 skill**。fstar 装在 `~/.claude/skills/` 属普通 skill，受影响 |
| **清单里算成本的** | `- ` 前缀 + `: ` 分隔符 + **skill 名** + 插件前缀/目录作用域后缀 + 描述 + `" - "` + `when_to_use` + 换行。**不算**目录路径、marketplace 名、文件内容 |

**本机实测**（`~/.claude/skills`，338 个可读 SKILL.md）：

| 指标 | 值 |
|---|---|
| skill 数 | 338 |
| 描述总字符 | 90,930 |
| 完整清单字符（名 + 分隔符 + 描述） | 97,853 |
| **仅名字的清单字符** | **6,247** |
| 默认预算（272k 上下文） | 10,880 |
| 超过单条 1536 上限的 | 0 |
| 已设 `disable-model-invocation` 的 | 0 |

**关键推论**：**339 个 skill 的名字就占掉预算的 57%**，留给描述的空间只有约 4,600 字符（还要先扣内置 skill 的完整描述）。**「把 fstar 描述写短」救不回来**——fstar 的 13 条描述无论如何都会被别的 skill 挤掉。

#### 4.1.2 fstar 的缓解方案（据此重做）

| # | 措施 | 做法 | 归属 |
|---|---|---|---|
| 1 | **描述极简** | 每条描述 ≤ **200 字符**（不是 token；清单里成本 = `len(desc) + 2`），13 条总量 ≤ 2,600 字符 | workflow-content |
| 2 | **首次调用清单** | 安装后提示逐个调用一次 13 个 `/fstar:xxx`。**这是最关键的一条**：任一次调用都会写入 `skillUsage`，分数 > 0 后永久优先于 328 个从未使用的 skill | package-install |
| 3 | **预算体检** | `fstar doctor` 按上表公式重算：读 `~/.claude/settings.json` 的 fraction → 算预算 → 统计 `~/.claude/skills` 的名字与描述字符 → 判断 fstar 的 13 个 skill 会不会被降级 → **明确告警**（含建议动作），不静默 | package-install |
| 4 | **提升预算（可选）** | 建议把 `skillListingBudgetFraction` 调到 `0.03`（272k 上下文下 32,640 字符）。`fstar doctor` 可检测到偏低时提示，**由用户确认后才写** | package-install |
| 5 | **手动专用 skill** | 只打算手动调用的 skill，在 SKILL.md 里设 `disable-model-invocation: true` → 消耗 0 字符 | workflow-content |
| 6 | **不覆盖用户配置** | 写 `~/.claude/settings.json` 时只**追加**自己需要的条目；不动用户已有的 `skillOverrides` / `skillListingBudgetFraction` 值 | package-install |
| 7 | **按项目排除** | 若某项目不需要 fstar，在该项目的 `.claude/settings.local.json` 写逐个 `skillOverrides: {"fstar-xxx": "off"}`——fstar 可提供生成命令 | package-install |

**注**：`SLASH_COMMAND_TOOL_CHAR_BUDGET` 环境变量可绕过 fraction 直接指定字符预算（2.1.311 有效），但**未文档化**，不作为受支持的方案，仅在用户明确需要硬上限时提及。


---

## 五、审计发现的三个事实

### 5.1 `context.jsonl` / `history.jsonl` 在 Trellis 里不存在

`grep -rn "context\.jsonl\|history\.jsonl" .trellis/scripts/` → **零命中**。Trellis 实际只有 `implement.jsonl` 和 `check.jsonl` 两个清单文件。

**此前研究文档写错了**：`research/tools-capabilities.md` §5「记录要求」写的是「`context.jsonl` 加 `capability` + `tool` 字段」和「`history.jsonl` 记录工具变更事件」——这两个文件 Trellis 没有，fstar 若照此设计会凭空多两个数据格式。已修正：fstar 的工具记录落到 `task.json` 的 `capabilities[]`，工具变更事件落到 `~/.fstar/tools.yaml` 的 `detected_at` 与 `history` 段。

### 5.2 task.json 有 4 个只写不读的死字段

`dev_type`、`scope`、`relatedFiles` 全仓库无消费方（见 §2.1 表）。fstar 不继承。

### 5.3 文档与实现有漂移

`workspace/index.md` 描述了 `workspace/{developer}/tasks/*.json` 和 `archive/`，但 `paths.py` 里没有对应路径，实际不存在。**审计以写盘路径为准**。

---

## 六、待定项

| # | 待定 | 影响 | 状态 |
|---|---|---|---|
| 1 | **宿主资源装在哪一层** | 决定 `fstar init` 写什么、跨项目可用性、以及 skill listing 预算的占用范围 | ✅ **已定：用户级**（2026-10-27）。见 §4.1 |
| 2 | **要不要会话日志（journal）** | — | ✅ **已定：不采用**。与 `directory-proposal.md` 的删减建议一致；任务历史由 `task.json.events[]` + `acceptance/` 覆盖，跨任务回忆由 `knowledge/` + `fstar-recall` 覆盖 |
| 3 | **归档时自动 git commit 吗** | — | ✅ **已定：默认 `false`**（`config.yaml` 的 `auto_commit`）。工具不该擅自改用户的 git 历史；需要时由用户显式开启 |
| 4 | 数据格式版本的迁移策略 | `.fstar/.schema-version` 升到下一版时，旧项目怎么办（自动迁移 / 提示迁移 / 拒绝操作） | 留待 `package-install` 子任务设计 |
| 5 | `evidence[]` 的 `fingerprint` 怎么算 | 内容哈希？变更指纹？与什么对比才判 stale | 留待 `core-commands` 子任务设计 |
| 6 | `skillOverrides` / `skillListingBudgetFraction` 的确切语义与配置位置 | 决定 §4.1 的「预算体检」怎么实现、能否引导用户策展 339 个 skill | 设计阶段核实 |
| 7 | `task.json.events[]` 的事件粒度与容量上限 | 决定追加式事件数组的字段与裁剪策略 | 留待 `core-commands` 子任务设计 |

---

## 七、一句话总结

**Trellis 的数据格式里，值得继承的是「形状」而不是「字段」**：清单用 jsonl 一行一条、任务用目录名表达归属、归档按月整棵移入、spec 索引带触发条件——这四条 fstar 沿用。**其余全部重造**，因为 fstar 的状态模型（7 阶段 + 证据 + 租约 + 验收闸门）与 Trellis 的 3 状态模型没有交集，硬套只会背着死字段走。
