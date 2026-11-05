# 工具分类器实施计划

> 本文件是 Trellis 子任务 implement.md；产品任务执行计划为 plan.md，不得因本文件名生成产品 implement.md。

## 当前状态与必读

2026-10-30 首轮实现已交付（实施者，经 `trellis-implement`）：`src/fstar/tool_classifier.py`（L1 清点/L2a 注册表 strong/L2b 探针 weak/L2c 残渣/三层 observation/proposals，零副作用）、`resources/registry/` 六个初始条目（codegraph/gh/qmd/psql/sqlite3/pytest）、`tests/test_tool_classifier.py` 44 项专项测试全部通过；全库 314 项中仅 `tests/test_tools.py` 3 项 T9 壳测试失败——它们以"classifier 尚未交付"为前提（`tools_classifier_unavailable` / 伪造目录内 ImportError），分类器交付后该前提在进程内不可复现；`tools.py`/`test_tools.py` 归 tool-binding 独立检查者所有，本任务未改，需协调者定夺这三项壳测试的归属调整。compileall 通过；真实 CLI 子进程 smoke（临时 user/runtime 根）返回合法 `fstar.tools.scan.v1`（4 提案、真实工具分类）；`content.validate_resources` 对 `resources/registry/` 零 RESOURCE_EXTRA；确定性双跑一致、仅 now 变化仅 detected_at/observation at 变化（真实 PATH 下验证）。写入已停，交独立 check。

2026-10-30 独立 check 完成（`trellis-check`）：核对全部 AC 与父设计后修复 7 项本范围缺陷并补回归（44→51 项专项测试）——(1) version_cmd/minimal_calls argv 锚定不一致：`{tool}` 首 token 被复制成双首参、裸旗标 minimal_call 被丢旗标，统一为 `_anchor_argv`（全 token `{tool}/{path}` 展开后再锚定）；(2) 生产缺省 MCP 配置路径误用 `user_root/.claude.json`、skill 目录误用 `user_root/skills`，改按子设计 §3 为宿主 `Path.home()/.claude.json` 与 `~/.claude(skills)/~/.codex/skills`；(3) 安装包注册表把 `--version` 声明为 codegraph/psql/pytest 能力 minimal_call（"有 CLI 即有能力"的虚假 verified），改回 `{}`（sqlite3 保留只读 `SELECT 1`）；(4) 探测 env `PATH=""` 使所有 `#!/usr/bin/env <interpreter>` 工具（codegraph/qmd 为 node 脚本）假失败 127，改为仅透传 `os.environ["PATH"]`、其余变量一律不传；(5) 不完整 host_snapshot 事实（verified 无 evidence_ref、minimal_call verified 无 call_id）原样透传违反诚实规则，改为定位诊断 `tools_scan_host_fact_invalid` 并跳过；(6) host-backed discoverable 的 evidence_ref 一律标 `host-config:`（host_snapshot/skill 来源错标），改为按来源 `host-snapshot:`/`host-config:`/`skill-dir:`；(7) 显式 `tool: null` 解绑在每次扫描被重新提案（把用户已拒绝的绑定反复重提），改为仅对缺键能力提案。专项 51/51 OK、全库 323/323 OK、compileall 通过、`content.validate_resources` 0 issue、真实 CLI 子进程 smoke（临时 HOME/user/runtime 根）scan.v1 10 工具/4 提案、双跑结构一致（仅 detected_at/observation at 随 now 变化）。写入已停，交协调者。

实施/check 均须完整 Read 父 `../10-25-fstar-workflow-design/{prd,design,implement}.md`（父 design 注入截断必须补读全文），再读本子 prd/design/implement 及 JSONL 所列规范/研究依据。研究稿旧 code-text、turn-context、AI 分类例外以当前父文档为准。用例审批已撤回，check 直接按需求补测试并运行，可自修本范围生产/测试代码。

开工定点核对实际代码（不放入 JSONL）：`src/fstar/tools.py` 的 `SCAN_SCHEMA`、`_handle_tools_scan` 校验的五个必备键、`_classifier_scan` lazy import、`validate_tools`、`build_binding_proposal` 签名、`FALLBACKS`；`src/fstar/config.py` 的 `parse_config` 支持子集；`tests/test_tools.py` 的 `_fake_classifier`/SCAN_SNAPSHOT 模式；`src/fstar/runtime/inject.py` 的 `resource_root()`。tools.py 若被并行修改，核对公共 API 差异再消费，绝不改 tools.py。

前置 `tool-binding` 已交付并过独立 check；`fstar tools scan` lazy import 壳已就绪（缺 classifier 时稳定报 `tools_classifier_unavailable`）。

## 所有权与依赖交接

| 所有者 | 边界 |
|---|---|
| tool-classifier（本任务） | `src/fstar/tool_classifier.py`、`resources/registry/*.yaml`、`tests/test_tool_classifier.py`；零 CLI/runtime/config 改动 |
| tool-binding | 只读消费：公共常量、`validate_tools`、`build_binding_proposal`、`load_tools`；绝不调用 `apply_binding`（确认流归用户/fstar-tools） |
| init / project-layout | 后续调 `scan_tools` 取候选与提案；本任务不改 project.py |
| runtime / session-context | 轻检查已存在；本任务零 runtime 改动 |
| package-install | 后续分发 `resources/registry/`；本任务只提供目录内容，不动安装逻辑 |
| e2e-verify | 真实宿主扫描留其执行；本任务测试不宣称宿主验证完成 |

## 执行顺序

| ID | 工作/完成判据 | 依赖与验证 |
|---|---|---|
| TC-I1 | 核对 tools.py 公共 API 与 scan 壳校验规则（五必备键/schema 常量）、锁定模块所有权与资源路径；空 `scan_tools` 骨架经 lazy import 壳取回最小 scan.v1 | 首先；经既有 T9 模式注入验证往返 |
| TC-I2 | `fstar.tool.registry.v1` 加载器：parse_config 解析、键/枚举/能力校验、用户 registry.d 覆盖安装包、坏文件诊断跳过；初始安装包注册表条目 | I1；AC-03/07 |
| TC-I3 | L1 清点（受控 PATH/MCP 配置只读解析/skill frontmatter）+ 失败隔离诊断 | I1；AC-02 |
| TC-I4 | 探测安全执行器：白名单旗标/注册表声明命令、列表 argv、空 cwd、超时、受限 env、输出截断 | I1；AC-05；不执行未知工具命令 |
| TC-I5 | L2a 注册表匹配（strong）+ L2b 维度探针（weak）+ L2c 残渣（none/unclassified） | I2–I4；AC-03/04 |
| TC-I6 | 三层 observation 产出（含 fixture 最小调用：符号 file:line、只读查询、隔离测试）+ host_snapshot 消费与网络未核实诊断 | I4/I5；AC-05 |
| TC-I7 | proposals 生成（strong 且目标未绑定，经 build_binding_proposal）+ 零副作用断言（前后目录集合不变） | I5；AC-06 |
| TC-I8 | 确定性回归：固定快照两次一致、仅 now 变化仅 detected_at 变化；全量测试、受影响回归、compileall、临时根 CLI smoke | I1–I7；AC-01/08；交独立 check |

## 测试矩阵

统一 unittest、TemporaryDirectory、固定 `now`、注入受控 PATH/env、桩可执行文件；不访问真实 `~/.fstar`、不联网、不执行真实宿主工具。

| ID | 场景与预期 |
|---|---|
| T1 | 空 PATH/空注册表/无 host_snapshot：tools 空、diagnostics 说明来源；非错误 |
| T2 | 注册表 YAML 实际 parse_config 解析与往返；坏 schema/未知能力/块映射序列给定位诊断；用户 registry.d 同 ID 覆盖 |
| T3 | L1 候选清单含名/类型/版本；探测失败（权限/超时/坏 JSON）隔离为诊断，不中断其他来源 |
| T4 | 注册表 strong、探针 weak（pattern 命中各维度各验一例）、残渣 none/unclassified；探针永不产生 strong |
| T5 | 未知工具除 `--version/--help` 外零执行；注册表声明命令才运行；执行约束（列表 argv/空 cwd/超时/env 截断）有测试 |
| T6 | observation 三层如实：verified 有 evidence_ref、failed 有 reason、minimal_call verified 有 call_id；MCP/skill 无宿主时仅 discoverable、其余 unknown |
| T7 | fixture 最小调用：code-structure 符号 file:line 比对、data-access 只读查询无写 SQL、test-execution 隔离 fixture；网络层无 host_snapshot 时 unknown+诊断 |
| T8 | proposals 仅 strong 且未绑定生成、diff 完整含工具快照；前后目录集合不变、无绑定写入 |
| T9 | 固定快照两次结果一致；仅 now 变化仅 detected_at 变化；AI 不在路径（无模型调用/无自然语言判断） |
| T10 | 经既有 lazy import 壳注入本模块，CLI `tools scan` 返回真实 scan.v1；schema/五键齐全；Python 3.9 compileall；`content.validate_resources` 不因 registry 新目录报 RESOURCE_EXTRA；全库回归 |

## 实施期验证命令

工作目录为项目根；只供实施/check 执行，本次规划不跑产品测试：

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_tool_classifier.py'`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall -q src/fstar tests`
- CLI 子进程（临时 cwd、全局选项在子命令前）：`python3 -m fstar --json --user-data-root <temp-user> --runtime-root <temp-runtime> tools scan`

记录实际环境、命令、结果、耗时/重跑数与未执行项；不得预填"通过"。

## 收工与回滚

独立 check 按全部 AC 检查并修本范围，按影响回归；最终核对父 implement #7 及集成 #25/#26。交付说明列公共 API、registry 格式与初始条目、探测安全规则、测试证据与未覆盖项（真实宿主观察留 e2e）。代码/资源回滚不自动改用户 registry.d 或已确认绑定。核心/runtime 接口冲突报协调者；常规实现细节不重新申请产品批准。子任务随父整体检查与归档，不单独归档。
