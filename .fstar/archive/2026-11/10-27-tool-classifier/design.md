# 工具分类器技术设计

## 1. 权威、边界与所有权

完整读取父 `../10-25-fstar-workflow-design/{prd,design,implement}.md`；父 design 注入截断时必须 Read 补齐全文。本子任务独占：`src/fstar/tool_classifier.py`、`resources/registry/`（安装包注册表数据）、`tests/test_tool_classifier.py`。**禁止**修改 `src/fstar/tools.py`、cli、runtime/hooks/dispatch、config/tasks/evidence/store——`fstar tools scan` 的 optional handler 与 lazy import 壳（`tools._classifier_scan` / `_handle_tools_scan`）已交付并验证，本模块只需暴露 `scan_tools` 并返回合法 `fstar.tools.scan.v1`。

消费的 tools.py 公共 API（只读复用）：`CAPABILITIES / TOOL_KINDS / MATCH_LEVELS / BASIS_KINDS / SCAN_SCHEMA / PROPOSAL_SCHEMA`；`validate_tools`（校验扫描产出的 Tool/Match 快照）；`build_binding_proposal`（生成提案，绝不调用 `apply_binding`——确认流归调用方）；`load_tools`（读取项目/用户 tools.yaml 现状，提案-only 前提下属读操作）。注册表文件用 `config.parse_config` 解析；一律 Python 3.9 标准库 + `from __future__ import annotations`。

资源根复用 `runtime.inject.resource_root()` 的解析模式（`Path(__file__).resolve().parents[3] / "resources"`），不硬编码仓库路径；`resources/registry/` 是新增资源目录，不属 `content.validate_resources` 的固定清单（skills/roles/templates/references），新增不触发 RESOURCE_EXTRA——收工时核对一次该不变量。

## 2. scan.v1 输出契约

```text
scan_tools(*, project_root: Path, user_root: Path, host_snapshot: dict|None, now: str|None = None) -> dict
```

返回 `fstar.tools.scan.v1`：

| 字段 | 内容 |
|---|---|
| `detected_at` | ISO-8601 UTC；`now` 注入则用之（确定性测试），否则实时 UTC |
| `tools[]` | Tool 形状（tool/kind/version/capabilities[]），L1+L2 全部产出；Match 遵守 `basis_source` 约束：registry→strong 或注册表声明的 weak/none、probe→仅 weak、unclassified→none |
| `observations[]` | Observation 形状（tool/capability/layer/status/at/scope/evidence_ref/reason/call_id）：discoverable 多为 verified（附来源 path）；client_loaded/minimal_call 按维度探测结果，未核实为 unknown 且 reason 说明 |
| `proposals[]` | `fstar.tools.proposal.v1`：仅 strong 候选且目标层（项目>用户）该能力缺绑定时生成；不落盘 |
| `diagnostics[]` | 探测失败（权限/超时/坏配置/坏注册表）与网络未核实事实的如实记录 |

scope 用 `{project: str|None, host: <事实来源>, session: None}`；未提交任何 proposal 时目标层实际未写。扫描零副作用：不 mkdir、不写文件、不安装、不联网（白名单 `--version/--help` 除外，且仅对本地可执行）。同一候选在 tools[] 唯一（tool ID 去重，MCP/PATH/skill 同名冲突记诊断）。

## 3. L1 清点与探测隔离

| 来源 | 只读做法 |
|---|---|
| PATH | `shutil.which` 按注册表+内置候选名单定位；绝对路径、不执行直到 L2/验证需要 |
| MCP | 解析宿主 JSON 配置（缺省 `~/.claude.json` 的 `mcpServers`，可用 `host_snapshot` 覆盖）；只读枚举，不连接 |
| skill | 列宿主 skill 目录的 `SKILL.md` frontmatter `name/description`；fstar 自身 12 skills 不计入 |

每类失败（PermissionError、超时、JSON 解析失败、目录缺失）记诊断 `tools_scan_source_failed{source, reason}`，不中断其他来源。版本获取仅限注册表条目声明的安全命令（见 §6）；未知为 null。

## 4. L2a 注册表与用户覆盖

安装包 `resources/registry/<tool>.yaml`（fstar 维护）；用户 `<user_root>/tools/registry.d/*.yaml` 同 ID 覆盖安装包条目。每目录一条目；无注册表 → 空 L1 候选，经诊断说明，不是错误。

`fstar.tool.registry.v1` 格式（可经实际 parse_config 解析：复杂值单行 JSON flow）：

```yaml
schema: "fstar.tool.registry.v1"
tool: codegraph
kind: cli
capabilities: [{"id": "code-structure", "match": "strong", "basis": "symbol-level definition/reference/impact", "basis_source": {"kind": "registry", "reference": "registry/codegraph.yaml@v1"}}]
version_cmd: ["--version"]
```

| 字段 | 约束 |
|---|---|
| `tool` | 非空稳定 ID |
| `kind` | cli\|mcp\|skill\|builtin |
| `capabilities[]` | Match 子集：id∈五能力、match=strong\|weak\|none、basis、`basis_source={kind: registry, reference: 本文件}` |
| `version_cmd` | 可选 argv 列表（如 `["--version"]`）；允许 pattern（tool/加 CLI 名首 token）便于复用 |

加载：文件经 `parse_config`，验证键集合/枚举/能力 ID；坏文件抛 DomainError `tools_registry_invalid`（带 path/line），由扫描记入诊断并跳过该文件（用户坏注册表不得静默消失）。内置安装包注册表含 Claude Code/Codex 两宿主已核实工具的初始条目（见 implement.md TB→TC 条目）。

## 5. L2b 通用探针（仅 weak）

对 L2a 未覆盖且自述可得的候选，按维度模式匹配工具自述文本（CLI `--version`/`--help` 输出、SKILL.md description、host_snapshot MCP tool 描述）：

| 能力 | 模式（命中任一即 weak） |
|---|---|
| code-structure | `(definition\|reference\|callers\|impact\|symbol).{0,60}(tree\|graph\|lookup\|index)` 等 |
| web-research | `search.{0,30}web\|fetch (url\|page)\|web search` |
| knowledge-retrieval | `search.{0,30}(knowledge\|documents?\|memory\|notes\|index)` |
| data-access | `sql\|schema.{0,30}(query\|inspect)\|database.{0,30}query` |
| test-execution | `run tests?\|test runner\|execute test` |

匹配一律 `{match: weak, basis_source: {kind: probe, reference: "probes/<capability>#pattern"}}`，绝不升 strong（validator 已强制 probe≠strong，schema 层不可违规）。探针失败记诊断，不中断。自述不可得（无 `--help` 输出、SKILL.md 无描述、host_snapshot 无该工具）→ L2c。

## 6. 探测安全规则（执行边界）

**未知工具零执行**：仅当 (a) 注册表显式声明该命令，或 (b) 在白名单只读旗标内（`--version` / `--help`，对扫描候选的本地 CLI）时才运行外部命令。绝不执行工具自述的命令或参数。

子进程约束：列表 argv（无 shell=True，shell 元字符无意义）；`cwd` 为空临时目录（防恶意脚本依赖 cwd）；`timeout` 默认 5 秒（TimeoutExpired 视为探测失败，不重试后静默放行）；受限 env（仅 PATH 传播所需，不含凭据）；隔离 stderr/stdout 截断（长输出记 diagnostic，不写入分类结果）；退出码非零/异常 → 失败诊断，不装作成功。同时探测多个候选互相隔离，一个失败不影响其他。**网络零调用**：模块不 import 网络库，不执行任何网络命令；网络相关可用性（web-research 的 client_loaded/minimal_call）仅在 host_snapshot 提供相应观察时报告，否则如实 unknown，并在 diagnostics 声明为宿主供给未核实事实。

**不执行注册表未声明的只读样板查询**：data-access 的最小真实调用只对已知模式（psql 等注册表声明工具）的只读连接信息发起，绝不执行写 SQL；test-execution 只跑隔离 fixture 中的已知测试命令，不跑任意项目测试。

## 7. L2c 未分类候选与提案

L2a/L2b 均未命中 → Tool 条目带 `{match: none, basis: "self-description excerpt", basis_source: {kind: unclassified, reference: "probes/unclassified#residual"}}`，不自动绑定。用户路径：(a) 在 `registry.d/` 写一行注册表条目（重启下次扫描生效）；(b) 经 fstar-tools 走确认流绑定（分类确认与绑定确认独立，已由 tools.py 强制）。

proposals 生成条件：该工具某能力 match=strong 且目标层（项目未 init 时为用户层；已 init 且项目 tools.yaml 缺该能力键时为项目层）该能力未绑定。提案经 `tools.build_binding_proposal(target, loaded, changes, reason, tools=快照)` 生成，reason 为"registry-declared strong match for <capability>"；完整提案含 diff 与快照交调用方显示，扫描绝不调用 apply_binding。

## 8. 三层验证事实

| 能力 | discoverable | client_loaded | minimal_call |
|---|---|---|---|
| code-structure | which/注册表定位 | `--help` 无错误输出 | fixture 源文件抽已知符号→查工具→比对 `file:line` |
| web-research | which | `--help`/host_snapshot 供给 | 仅 host_snapshot 供给（offline 为 unknown+诊断） |
| knowledge-retrieval | which | `--help` | 查询已知本地文档路径 |
| data-access | which | `--help` | 只读样板查询（如 `select 1`/schema 列表），绝无写 SQL |
| test-execution | which | `--help` | 隔离 fixture 单个已知测试，退出码可记 |

MCP/skill 类候选：无宿主连接能力时仅 discoverable 可 verified，其余 unknown，理由为"host adapter not available"；host_snapshot 缺失不是错误。observation 的 `status` 如实：verified 须有 evidence_ref（fixture path / 输出摘要哈希），failed 须有 reason；minimal_call 的 verified 须有 call_id（真实最小调用标识，非扫描标识）。**scan 不自动写 detected_at 到 tools.yaml**：detected_at 是本次快照时间，写入发生在确认后的 apply_binding。

## 9. 确定性与测试策略

扫描结果除 `detected_at` 外必须纯函数于输入（PATH 快照、注册表、host_snapshot）。固定输入快照两次运行结果一致（排除 detected_at，独立注入 `now`）；对输出中所有绝对路径仅存在于 diagnostics/observation evidence_ref，无机器路径混入 tools[]（工具快照可移植）。单元测试注入受控 PATH（TemporaryDirectory + 桩可执行脚本）、受控注册表目录、host_snapshot 字典、固定 `now`；绝不访问真实 `~/.fstar`、绝不执行真实宿主工具、绝不联网。CLI 集成测试经既有 `tools scan` lazy import 壳注入 `fstar.tool_classifier`（参照 `tests/test_tools.py` 的 `_fake_classifier` 模式）注入本模块真实实例，验证往返。

## 10. 集成交接

- init（project-layout 所有者）：直接调 `scan_tools` 取候选与提案，提示绑定、确认后调 apply_binding；本任务不改 init。
- session-context（runtime 所有者）：轻检查已存在（存在性 + detected_at 过期），本任务零 runtime 改动。
- e2e-verify：在真实宿主场景跑 `fstar tools scan`，补宿主真实观察；单测内宿主验证不得宣称真实宿主通过。
- knowledge-base：消费 knowledge-retrieval 的 resolution，不消费扫描。
- package-install：分发 `resources/registry/`，升级不覆盖用户 registry.d；本任务只提供目录内容。

## 11. 风险

| 风险 | 缓解 |
|---|---|
| 注册表条目覆盖全新未知工具 | L2b 探针召回部分新工具（weak）；L2c 显式留用户决定 |
| 白名单旗标被恶意可执行文件滥用 | 空临时 cwd、受限 env、超时、截断输出；白名单旗标仅用于版本/自述获取，不进入 trusted 数据 |
| host_snapshot 形状漂移 | 未识别形状记诊断并跳过，不臆测 |
| 注册表维护成本 | 初始条目限宿主已核实工具；用户 registry.d 覆盖未知工具 |
| diagnostics 信息泄漏 | 不存凭据/绝对用户路径于 tools[] 快照；diagnostics 的 evidence 引用仅记相对/受控路径 |
