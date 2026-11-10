# init 时的能力绑定由 agent 完成

## 背景

`fstar init` 已经会运行只读的工具扫描并返回 `tool_proposals`，但当前流程把
“选哪个工具绑定到哪个能力契约”留给用户手动决定。实际使用中：

- 扫描对 347 个全局 skills 中的 332 个给出 `none` 匹配（描述无法被维度
  探针归类），用户面对一长串候选无从选择；
- fstar 的绑定模型是“5 个能力契约各绑 1 个工具”，用户不需要也记不住
  每个场景该选谁；
- 用户希望操作更少：初始化时由 agent 识别、分批归类、能确定的就绑定，
  不确定的留空，最后一次性汇报，用户只做一次确认。

进一步的分析（2026-11-10）确认了一个缺口：即使 init 时写好了
`tools.yaml`，会话与 worker 注入也不包含解析后的绑定表——绑定对模型
不可见等于没有绑定（模型只有在主动调用 fstar-tools 技能时才读得到）。
这正是历史上“模型不自动使用对应工具/规范”的根因之一：规范写在易失
上下文里，会话一长、一压缩就被遗忘。本任务把绑定表接到必然注入通道上。

## 范围

### R-001 init 技能驱动能力绑定

`resources/skills/fstar-init/SKILL.md` 增加“Initial capability binding”阶段，
明确要求 agent 在 init 骨架校验完成后：

- 候选集 = 宿主 skill 列表（全局 `~/.claude/skills` + 项目
  `.claude/skills`）+ `tool_proposals.tools` 中的 CLI 工具；
- 分批（30–50 个/批）阅读描述；长清单交给后台 agent，主对话保持可用；
- 对 `code-structure`、`web-research`、`knowledge-retrieval`、
  `data-access`、`test-execution` 五项各选**最多 1 个**工具；
- 优先 registry `strong` 匹配；`weak` 或可核实的工具描述可作为依据；
  证据不足则**留空**，不得用关键词巧合硬绑；
- 汇总一次：选中项（场景→工具→依据）、跳过项数量与原因、未绑定场景；
- 用户确认一次后，通过 `tools_bridge` prepare → apply 写入；
- 用户拒绝则保持零 `tools.yaml`，并说明扫描结果仍可查看。

验收：

- Given 一个已初始化的项目与全局 skills
- When agent 执行 fstar-init 技能
- Then 输出一份聚合汇总，且只在用户确认后写 `.fstar/tools.yaml`
- And 每项能力最多 1 个绑定
- And 不属于任何能力的 skill 不进入绑定

### R-002 绑定层级固定为项目级

- 技能明确禁止创建或修改用户级 `~/.fstar/tools.yaml`。
- 写入路径固定为 `<project>/.fstar/tools.yaml`。

验收：

- 拒绝或未确认时，用户级与本项目 `tools.yaml` 均不存在/未变化。

### R-003 修正 routing 中的过期描述

`resources/runtime/routing.md` 中 “The current CLI initializes the skeleton
but does not yet run that scan or apply collected context; report those gaps.”
与现状不符（CLI 已运行扫描）。改为：初始化运行扫描；应用绑定仍需用户确认，
且只写项目级。

验收：

- routing 文本不再声称 CLI 不运行扫描
- 最小闭环与扩展协商语义不变

### R-004 会话与 worker 注入只读绑定表

新增 `runtime/inject.py` 的 `bindings_input()`：解析项目级 + 用户级
`tools.yaml`（复用 `tools.load_tools` + `tools.resolve_bindings`），渲染成
约 8 行的能力→工具表，注入两处：

- `session_context`（hooks.py）：会话启动/清空/压缩后必然重注入，绑定表
  因此在压缩后存活；
- `worker_context`（hooks.py）：dispatch 前注入，四个角色 worker 可见。

边界：

- **不受授权门禁**：与 capabilities.md “发现默认开、使用才授权”一致；
  读表是发现，写 `tools.yaml` 才需要 tool-capability grant + 精确确认。
- **只读**：缺文件 = 全部 unbound（正常状态）；无效文件不破坏被动注入，
  注入一行修复指引；`_light_tool_check` 仍负责缺文件/过期提示。
- 注入文本自带一行说明：“任务匹配某能力时用绑定工具；unbound 意味着
  没有合格工具，按契约降级而不是随便换一个”。

验收：

- Given 项目 `tools.yaml` 绑定 code-structure→codegraph
- When session_context / worker_context 运行（无任何 grant）
- Then 注入文本含 `code-structure: codegraph` 与 `web-research: unbound`
- And 缺失层级时五个能力全部显示 unbound
- And 无效 tools.yaml 注入修复指引而非报错

## 不做

- 不新增 `fstar tools bind` 或其他命令（用户明确要求减少命令）。
- 不改变 `tools.yaml` 的“每能力单工具”数据模型。
- 不改变 `fstar init` 的零写入/提案语义：绑定写入发生在 agent 与用户
  确认之后，由现有 `tools_bridge` 完成。
- 不回填历史项目已存在的绑定。

## 验证

- `PYTHONPATH=src python3 -m unittest discover -s tests -t .` 全绿
- `node --test tests/test_package.cjs` 全绿
- `node scripts/build-package.cjs` 重建清单
- 检查 `fstar-init/SKILL.md` 与 routing 的最终文本
