# Python 工具分类器

## Goal

交付 Python 确定性分类器 `fstar.tool_classifier`：L1 存在性清点（PATH 可执行 / MCP server / 已装 skill）→ L2a 声明式注册表 strong → L2b 维度通用探针 weak → L2c 未分类候选，供 init / `fstar tools scan` / e2e 消费；三层可用性以事实（observation）形式产出。AI 永不进入分类路径；扫描只读、提案-only，未确认不写任何绑定。

当前权威为父任务 `../10-25-fstar-workflow-design/{prd,design,implement}.md`（PRD §5、design §3.5–§3.6/§4、implement #7 与集成 #25/#26）。父 design 自动注入可能截断，实施与检查都必须 Read 补齐全文。第一版十子任务已有实施授权，本轮只刷新本目录五份规划文件，不 start、不写产品代码、不做 git。

## 前置依赖与所有权

依赖 `tool-binding`（已交付并过独立 check）：分类器只消费 `fstar.tools` 公共 API（五能力常量、Tool/Observation 形状、`build_binding_proposal`），独占 `src/fstar/tool_classifier.py`、`resources/registry/`（安装包注册表数据）与 `tests/test_tool_classifier.py`；不改 tools.py、不注册任何 CLI 命令（`fstar tools scan` 的 lazy import 壳已存在）。

## 需求

### TC-01 唯一入口与输出契约

`scan_tools(*, project_root, user_root, host_snapshot, now=None) -> dict`，返回 `fstar.tools.scan.v1`：`schema, detected_at, tools, observations, proposals, diagnostics`。tools 复用 tools.v1 的 Tool/Match 形状；proposals 为 `fstar.tools.proposal.v1`；不写任何文件、不建索引、不安装。`now` 可选注入以保证确定性测试（缺省用实时 UTC 时钟）。

### TC-02 L1 只清点、不判断

枚举 PATH 可执行文件、MCP server（只读解析宿主 JSON 配置及 host_snapshot）、已装 skill 目录（SKILL.md frontmatter），产出候选（名/类型/版本）。探测失败（权限/超时/坏配置）隔离为诊断，不中断整体扫描。版本仅经注册表声明的安全探测命令获得，未知为 null。

### TC-03 注册表优先级与格式

用户 `~/.fstar/tools/registry.d/` 优先于安装包 `resources/registry/`，同 tool ID 用户覆盖。注册表条目 `fstar.tool.registry.v1` 必须能用现有 `config.parse_config` 实际子集解析（复杂值单行 JSON flow），坏文件给定位诊断并跳过。strong 仅来自注册表依据（含用户注册表）。

### TC-04 探针只 weak、执行安全

L2b 用维度通用模式匹配工具自述（CLI 白名单旗标输出 / SKILL.md 描述 / host_snapshot 的 MCP tool 描述），命中一律 `weak`，`basis_source=probe`，永不升 strong。执行安全规则：只运行白名单只读旗标（`--version`/`--help`）或注册表显式声明的命令；绝不执行未知工具自述的命令或参数；列表 argv、无 shell、空临时目录 cwd、超时、受限环境；绝不发起网络调用。

### TC-05 三层可用性事实

按能力×工具产出 observation：`discoverable`（纯文件系统事实）、`client_loaded`、`minimal_call`。最小真实调用按维度选安全动作（code-structure 查 fixture 符号比对 `file:line`；data-access 只读样板查询、绝不写 SQL；test-execution 只跑隔离 fixture；web-research/knowledge-retrieval 不联网，缺宿主事实如实 unknown）。网络相关层仅在 host_snapshot 提供时报告，文档如实标注为未核实/宿主供给事实。

### TC-06 L2c 与提案

未命中两档的列为未分类候选（自述摘录进 basis，`basis_source=unclassified`），不自动绑定；用户手写 registry.d 一行或经 fstar-tools 确认。proposals 仅对 strong 候选且目标层该能力未绑定时生成，交 `tools.apply_binding` 在真实用户确认后提交。

### TC-07 性能与集成边界

完整扫描只发生在 init / 显式 `fstar tools scan`；session-context 轻检查（存在性 + detected_at）归 runtime 所有者（已存在），本任务零 runtime 改动、零新用户命令。分类路径不调用任何模型。

## 验收标准

- [ ] AC-01：固定输入快照（含受控 PATH、注册表 fixture、host_snapshot、固定 now）两次扫描结果完全一致；仅 now 变化时仅 `detected_at` 变化（回归测试）。
- [ ] AC-02：L1 产出候选清单（名/类型/版本），不做能力判断；探测失败隔离为诊断，不中断扫描。
- [ ] AC-03：注册表 strong、未注册探针 weak、两档未命中进入未分类候选；用户 registry.d 覆盖安装包条目；探针不得自行升 strong。
- [ ] AC-04：AI 不在分类路径——实现与测试不调用任何模型，无自然语言判断参与分类。
- [ ] AC-05：三层验证按维度选择安全最小调用；未知工具除白名单只读旗标外零执行；不执行写 SQL、不跑任意项目测试、不联网。
- [ ] AC-06：`fstar tools scan` 经既有 lazy import 壳取回 scan.v1；未确认不写绑定、不创建任何用户/项目文件。
- [ ] AC-07：注册表 YAML 经实际 `parse_config` 解析并往返；不支持的构造明确报错；坏条目定位诊断。
- [ ] AC-08：全部测试用临时根、受控 PATH/env、固定时钟与桩可执行文件，不访问真实 `~/.fstar`、不联网、不执行任意未知可执行文件。

## 范围外

不实现绑定确认流（tools.py 已有）、不新增 CLI 命令、不改 runtime/hooks/dispatch、不做宿主内真实 MCP/skill 调用（留 e2e）、不自动安装、不做 AI 辅助分类、不新增第六能力。init 消费 scan.v1 提案属后续所有者。代码回滚不自动更改用户已确认绑定。

## 依据

- 父任务 `design.md` §3.5–§3.6、§4.2–§4.5；`implement.md` §3 #7、集成 #25/#26
- 父任务 `research/tools-capabilities.md` §四（三层结构、L2 三档、三层验证脚本化、性能边界）；其旧 code-text/turn-context/AI 例外表述以当前父文档为准
- tool-binding 交付的 `resources/references/tool-bindings.md`（scan 协议、YAML 子集、Observation 契约）

## Notes

- 父任务：`../10-25-fstar-workflow-design/`（PRD、任务地图、跨子任务验收标准）
- 本文件为规划刷新稿，2026-10-30。
