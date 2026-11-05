# 工具分类器独立检查报告（trellis-check，2026-10-30）

检查对象：`src/fstar/tool_classifier.py`、`resources/registry/*.yaml`、`tests/test_tool_classifier.py`。依据：本子任务 prd.md/design.md/implement.md、父任务 `10-25-fstar-workflow-design` 全文（含 §3.6 三层分类、§4.2 数据格式、§4.5 所有权）、check.jsonl 所列规范。`src/fstar/tools.py`/`tests/test_tools.py` 归并行 tool-binding 检查者所有，本任务只读核对公共 API，未做任何改动。

## 逐项核对结论（dispatch 清单）

- 确定性（AC-01）：固定输入下结构完全一致；两次真实 CLI 子进程双跑仅 `detected_at` 与 `observation.at` 随注入 now 变化，其余逐字节相等。代码路径无 dict/set 迭代序输出（所有 glob/iterdir/servers 均先 sorted）、无随机源、无环境变量读取（唯一环境读取是探测 PATH 的透传，见缺陷 4）；时间仅来自注入 `now`。
- L1 只读清点：PATH 经 `shutil.which` 只读；MCP 仅解析宿主 JSON 的 `mcpServers` 键，绝不连接、绝不外发数据、其余键（含凭据类字段）一律不读；skill 仅读 SKILL.md frontmatter name/description；fstar 自身 `fstar-*` skill 排除。所有读取失败为隔离诊断，不中断其他来源。
- 注册表（AC-03/07）：真实 `config.parse_config` 解析；键/枚举/能力校验齐全；用户 `tools/registry.d/` 同 ID 完全覆盖安装包条目（user > package）；坏 schema/未知能力/解析错误均给含 path/line 的定位诊断并跳过，加载永不抛异常。非映射顶层文档（序列/标量）由 parse_config 自身拒绝，已实证。
- 探测安全（AC-05）：argv 恒为列表、无 `shell=True`、临时空 cwd、5s 超时（PROBE_TIMEOUT_SECONDS）、8 KiB 输出截断并记 `tools_scan_probe_truncated`、data-access 写 SQL（DROP/INSERT/UPDATE/DELETE/CREATE/ALTER…）拒绝并记 `tools_scan_probe_refused`、未知工具只跑 `--version/--help` 白名单、绝不执行工具自述命令。测试断言模块源级常量（env 形态、无 shell=True、TemporaryDirectory）+ 行为回归。
- weak-only 与残渣（AC-04）：探针层结构上只产 weak（tools.py `validate_tools` 对 probe 基 strong 直接报 `tools_invalid_schema`，模块自身 `basis_source.kind` 也只写 probe+weak）；残渣 tier=unclassified 只产 none，proposals 过滤 tier=="registry" 且 match=="strong"，弱/残渣永不提案（有专项回归）。
- proposals（AC-06）：仅对未初始化/未绑定目标层的 strong 候选经 `tools_api.build_binding_proposal` 生成；目标层选择（project 已初始化否则 user）正确；`apply_binding` 在本模块与测试生产路径零调用（仅 ProposalTests 一处测试直接调用以构造"已绑定"夹具）；前后目录快照不变断言零写入。
- 三层 observation 诚实性：MCP/skill 无宿主适配时 client_loaded/minimal_call 如实 unknown（"host adapter not available"）；网络能力无 host 事实时 unknown + `tools_scan_network_unverified` 诊断，扫描绝不通网；verified 必有 evidence_ref、minimal_call verified 必有 call_id、failed 必有 reason，且模块输出自检 `_check_observations` 强制执行。
- 零写入：测试前后目录集合（含 mtime）不变；真实 CLI smoke 临时根内除 Python 解释器自身字节码缓存外零文件产出，user/runtime 根均未被创建。
- 无 AI/网络导入：模块仅 import json/os/re/shutil/subprocess/tempfile/datetime/pathlib/typing + 包内 tools/config/models/store，无任何 HTTP/model 客户端；专项测试断言分类路径无模型/自然语言判断。
- `content.validate_resources(resources)`：0 issue，registry/ 无 RESOURCE_EXTRA。

## 发现并已修复的缺陷（均补回归）

1. argv 锚定不一致（`tool_classifier.py` `_anchor_argv`，替换已删 `_expand_argv`）：`version_cmd: ["{tool}", "--version"]` 把首 token 复制为双首参（桩实测 `$1` 收到 tool id 而非 `--version`，version 误为 null）；`minimal_calls: ["--version"]` 裸旗标被无条件替换为仅 `[path]`（旗标被丢）。统一为：先对全部 token 展开 `{tool}/{path}`，首 token 为锚（占位符/tool id/路径）则替换，否则前置路径，任何声明 token 不丢不重。回归：`{tool}` 首 token 锚定一次、裸旗标保留、argv 中段占位符展开。
2. 生产缺省宿主路径错位：MCP 缺省读 `user_root/.claude.json`（即 `~/.fstar/.claude.json`，永不存在的路径）、skill 缺省读 `user_root/skills`，违反子设计 §3（缺省 `~/.claude.json` 与宿主 skill 目录）。改为 `Path.home()/.claude.json` 与 `~/.claude/skills`、`~/.codex/skills`（常量 DEFAULT_MCP_CONFIG/DEFAULT_SKILL_DIRS），测试夹具同步注入临时 HOME 保证封闭。
3. 安装包注册表虚假 minimal_call：codegraph/psql/pytest 把 `["{path}", "--version"]` 声明为能力 minimal_call——`--version` 只证明二进制存在，不证明能力（AC-05 "有 CLI 因此能干活"的误判形态）。三文件 minimal_calls 改回 `{}`；sqlite3 保留只读 `["{path}", ":memory:", "SELECT 1"]`。回归断言安装包注册表无任何能力以裸 `--version` 作 minimal_call。
4. 探测 env `PATH=""` 造成假失败：受限 env 原为 `{"PATH": ""}`，使一切 `#!/usr/bin/env <解释器>` 前缀工具（真实宿主的 codegraph、qmd 均为 node 脚本）以 127 失败并记成诚实的 failed observation——结果本身诚实但判定错误。改为仅透传 `os.environ["PATH"]`，其余变量（HOME/凭据/配置路径）仍一律不传。回归：`#!/usr/bin/env sh` 桩在探测下正常解析。修复后真实 smoke 中 codegraph=0.9.3、qmd=2.8.3、gh=2.87.3、sqlite3=3.54.0。
5. 不完整 host_snapshot 事实透传（诚实性缺陷）：verified 事实缺 evidence_ref、minimal_call verified 缺 call_id 时原样透传成 verified，违反"verified 需证据"契约。改为定位诊断 `tools_scan_host_fact_invalid` 并跳过（按序继续找下一条匹配事实），永不整体失败、永不虚报。
6. host-backed discoverable 证据错标：host_snapshot 来源与宿主配置文件来源、skill 来源一律标 `host-config:`。改为按来源 `host-snapshot:`/`host-config:`/`skill-dir:` 前缀。
7. 显式解绑反复重提：`tool: null`（用户明确拒绝绑定）的旧代码用 `bound.get(id) is None` 判定"未绑定"而每次扫描重新提案。改为仅对缺键能力提案（present key 即用户决定），与 resolve_bindings 的 null 遮蔽语义一致。回归：显式 null 绑定文件下 proposals 为空。

## 验证记录（实际执行）

环境：macOS（Darwin 27.0）、系统 python3 3.9（Xcode CLT），项目根执行。

| 命令 | 结果 |
|---|---|
| `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_tool_classifier.py'` | Ran 51 tests, OK（首轮 44 → check 修复后 51，新增 7 项回归） |
| `PYTHONPATH=src python3 -m unittest discover -s tests` | Ran 323 tests, OK（协调者所述 314 为并行 owner 修复前基线；首轮 check 实测 316 已 OK，最终 323 全绿，无需跨所有者协调） |
| `python3 -m compileall -q src/fstar tests` | 通过（零输出） |
| `PYTHONPATH=src python3 -c "... validate_resources(resources)"` | 0 issue，registry/ 无 RESOURCE_EXTRA |
| 真实 CLI 子进程 smoke（临时 HOME/user/runtime 根，`--json ... tools scan`，双跑） | exit 0；`fstar.tools.scan.v1`；10 工具（codegraph/curl/gh/git/grep/jq/node/python3/qmd/sqlite3）、4 提案、90 observation、10 诊断（network_unverified/probe_failed/probe_truncated/source_empty）；双跑结构一致仅时间戳随 now 移动；临时根内零产品写入 |

缺陷 1/4 的复现均在临时目录内以桩可执行文件实证（复现→修复→复测），未触碰真实 HOME/宿主设置/git/网络/自动安装。

## 未覆盖与已知限制（如实记录）

- 真实宿主观察（宿主 MCP 连接、宿主 skill 目录真实内容）留 e2e-verify 子任务；本任务测试全程临时根 + 桩。
- macOS `~/.codex/skills` 未在真机验证其存在性（代码按目录存在则枚举、缺失则跳过处理）。
- 注册表 `basis_source.reference` 现产 `registry/codegraph@v1`（stem 无 `.yaml`），而参考文档 `resources/references/tool-bindings.md` 示例为 `registry/codegraph.yaml@v1`——纯文档一致性观察，非功能缺陷，留协调者定夺规范措辞。
- grep 在真实 PATH 下 `--version` 退出码 2（BSD grep 不支持该旗标），version 如实为 null、client_loaded 如实 failed——判定正确，非缺陷；如需改善需注册表为 grep 声明替代 version_cmd，属内容决策未自作主张。
- 探测超时 5s 下 timeout 用 `/bin/sleep 30` 桩回归覆盖；真实网络型工具不可探测由 `tools_scan_network_unverified` 明示。

写入已停于本报告与 implement.md 进度更新。
