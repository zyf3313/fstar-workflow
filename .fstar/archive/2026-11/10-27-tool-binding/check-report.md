# Check report — tool-binding (independent check)

检查者：trellis-check（独立检查），2026-10-30。检查前完整 Read 了父任务五份文件（prd/design/implement）与本子任务 prd/design/implement/check.jsonl/implement.jsonl，以及 `.trellis/spec/backend/index.md`（仍为待填模板，无已落地规范可引用）。工作目录不是 Git 仓库，`git diff` 不可用；未做任何 git 操作、未访问真实 HOME、未联网、未运行任意外部工具。

## Scope

检查并修复的文件（全部为本任务所有权范围）：

- `/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow/src/fstar/tools.py`
- `/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow/tests/test_tools.py`
- `/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow/resources/capabilities/{code-structure,web-research,knowledge-retrieval,data-access,test-execution}.md`
- `/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow/resources/schemas/tools.schema.json`
- `/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow/resources/references/tool-bindings.md`
- `/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow/resources/skills/fstar-tools/SKILL.md`

未改 core/config/cli/runtime/dispatch/tasks/store/models 的任何代码；所有核心 API 均按现状消费。

## 实际代码审查（非仅测试总数）

逐条核对了 TB-01–TB-07 与 AC-01–AC-10，重点结论：

- **TB-01/AC-01**：恰五份契约，每份七段（Definition / Decidable criteria / Three-layer verification / Recommended implementation / Common non-qualifying implementations / Fallback / Recording requirements）。判定要点可观察（file:line 可追、区分不存在与未索引、只读边界、命令+退出码可复现、原话来源可读）；每个维度的最小真实调用是安全且最小的动作（查询一个已知符号 / 读取任务所需单一来源 / 查询已知本地文档 / 授权只读 `select 1` / 隔离 fixture 单测），并明确“写 SQL 永不作为探针”“运行任意项目测试不是无副作用探针”。降级路径与 `tools.FALLBACKS` 逐字一致（结构测试断言归一化文本包含）。无第六能力（`code-text` 在代码、schema、契约、reference 中均被拒绝），无产物质量冒充能力。
- **TB-02/AC-02/03/04**：schema/示例经真实 `parse_config` 解析并通过 `validate_tools` 语义校验；reference 中的 yaml block 用真实 parser 解析后又经 `serialize_tools` 写回再解析，往返相等。整条能力事项覆盖、缺键继承、显式 `tool:null` 遮蔽（且保留本层 origin/确认快照）、默认仅 recommended（无 confirmation、binding_digest=null）均有测试。同名工具跨层不拼接（binding 与 tool 快照同层解析，返回 origin/path/digest）。缺文件=missing（digest=null）；空文件、乱码、目录代文件、不可读分别报 `tools_invalid_schema`/`tools_encoding_error`/`tools_read_error`；坏项目层不被用户层掩盖，且伪造的 layer 结果会被重新校验拒绝。块映射序列给出迁移提示（单行 JSON flow）。
- **TB-03/AC-05**：strong 仅 registry 或带确认的 user basis；probe 只能 weak；unclassified 必须 none；用户确认分类必须显式包含能力判断（不从我选了什么推断）。选中工具不提升 match（weak 选中后 match 仍为 weak）。三层 verified/failed/unknown 独立；verified 必有 evidence_ref、minimal_call verified 必有 call_id、failed 必有 reason；无观察=unknown（reason=not_observed）；跨工具/能力/作用域的观察不能拼成三层通过（scope 不一致时全部降为 unknown+scope_mismatch）；`now`+`max_age_seconds` 显式传入才判 stale。
- **TB-04/AC-06**：确认闸门覆盖完整 diff（changes+tools 快照）、精确 target/path、`validates`=proposal digest（digest 覆盖 reason）。无确认/agent actor/缺 quote 或 reference/裸 approved 字样（review）/scope 不匹配/旧 digest 均拒绝且不动文件、不留授权记录；并发文件变化与锁超时是 status=4 冲突；`os.replace` 失败保持原字节并清理临时文件；拒绝路径越界与符号链接。写入顺序：确认校验→锁→重读 digest→（已应用幂等检查）→digest 冲突→序列化回解析校验→再次拒符号链接→同目录临时文件+fsync+`os.replace`。已确认变更只改目标事项并同文件原子追加 confirmation+history。
- **TB-05/AC-07**：缺口报告含 missing_layers、每层 reasons、recommendations.source（指向 `capabilities/<id>.md`）、fallback；未绑定/有缺失层/match 非 strong 都产生 gap。扫描/提案/读取不安装、不联网、不创建元数据（T2 显式断言不建目录）。
- **TB-06/AC-08**：真实 TaskStore 往返（非 mock）——capabilities[] 追加、`capability_recorded` 统一事件封套（经 make_event/compact_events）、extensions/phase/acceptance/lease expires 不变；同 id 同内容幂等、不同内容 `tools_provenance_conflict`；缺/错/过期租约 `invalid_lease`/`expired_lease`；planning 相 `tools_task_not_active`；dropped `tools_task_dropped`；ref=None 提前返回 session_only 且目录集合不变。无新 task 顶层字段（capabilities 是既有 26 字段之一，事件走统一封套）。
- **TB-07/AC-09/AC-10**：仅 `fstar tools scan` 注册，handler 挂在 tools 父 parser 并被 scan 继承，先于 `_service` 分派；未 init 目录可报告。classifier 缺失=`tools_classifier_unavailable`（稳定非零），模块存在但内部 ImportError=`tools_classifier_import_failed`，不吞掉。固定快照经真实 `cli.main` 注入验证 `fstar.tools.scan.v1` 协议。help 只有 scan，无 bind/status/validate/install。测试全部用临时根/固定时钟/桩适配器。

### 实施者所记设计决策复核

- **幂等在 digest 冲突之前（already_applied 在 digest 移动后仍可返回）**：我用脚本构造了多种“陈旧授权重放”场景独立验证——(a) 绑定已被后续授权改为其他工具或 null：重放被 `tools_binding_conflict` 拒绝；(b) 工具被删除后重放：拒绝；(c) 用户把分类降级为 weak/probe 或版本升到 9.9.9 后重放旧 strong 快照：返回 already_applied 但**文件字节不变**，weak/新版本保持不变（幂等路径不重写 tools 快照）；(d) 解绑后又用新授权重新绑定同一工具后重放旧授权：返回 already_applied，但最终状态与最新授权完全一致，无任何字节差异。结论：`_already_applied` 只在历史存在同 source_id 同 diff 且当前绑定值与授权值一致时短路返回，且短路路径零写入，因此**不能**用陈旧授权重放一个“不同的变更”。同 source_id 不同 diff 一律 `tools_binding_conflict`。该顺序与契约一致（“已有明确授权直接复用，不重复审批”）。
- **规范写者重排=digest 冲突路径**：确认。任何导致字节 digest 变化的重写（包括仅改 reason 后由写者规范化）都会走 `tools_binding_conflict`，除非幂等短路命中（此时也零写入）。reason 由 proposal digest 覆盖（实测 reason 变化改变 digest），确认的 validates 绑定它。
- **TOCTOU**：我用 monkeypatch `os.replace` 在替换前一瞬间把目标换成符号链接做了攻击模拟——`_atomic_write` 的 `os.replace` 是对固定路径的原子替换，替换后目标不是符号链接，受害者文件未被写入，写者数据落在真实路径。符号链接拒绝在锁内对目标及其祖先执行，且在写入前再次执行。

## 缺陷与修复（本范围自修）

1. **`src/fstar/tools.py` `build_provenance` — 降级调用的 provenance 无法记录（TB-06/AC-08）**。能力显式未绑定（`tool:null`）时走契约降级路径的真实调用（如 literal search via `rg`）生成的记录 `tool=None`，`record_provenance` 以 `record.tool must identify the actual tool used` 拒绝，连 session-only 也拒绝——这使五份契约“Recording requirements”明确要求的“记录实际工具及降级情况”无法达成。更糟的是：能力已绑定但实际调用由**另一个**工具完成时，记录会**误命名为绑定工具**（把降级调用伪装成绑定调用）。修复：`call_record.tool` 显式命名实际使用的工具；未命名时默认绑定工具；实际工具≠绑定工具或未绑定时 `fallback=True`，`kind`/`version` 仅在实际工具即绑定工具时取自绑定快照；未绑定且未命名降级工具时明确报 `tools_invalid_call_record`。`resources/references/tool-bindings.md` 的 Provenance 节同步更新（单一格式权威）。新增三个回归测试（未绑定+命名降级工具可全程持久化；未命名拒绝；不同工具完成调用记为 fallback 且绑定字段保留）。
2. **`src/fstar/tools.py` `_assess_capability` — 最近观察选择按原始字符串比较 ISO 时间戳（AC-05）**。`max(candidates, key=lambda item: item["at"])` 在混合小数秒格式时排序错误（`"…09:00:00.500Z"` 字符串小于 `"…09:00:00Z"`），会把更晚的失败观察错当成更早的 verified 观察。修复：按 `_parse_iso` 解析后的时间比较。新增回归测试（`.500Z` 的 failed 晚于整秒的 verified，最终取 failed）。

未修复事项：无（两个发现均已修复并加回归）。

## 验证（实际命令与结果）

解释器：`python3` = Python 3.9.6（`python3.9` 可执行名不可用，与兄弟任务检查一致）。

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_tools.py'` — **80 通过，0 失败**（初检 75；+3 降级 provenance/时间比较回归，+2 classifier 交付后调整）。
- `PYTHONPATH=src python3 -m unittest discover -s tests` — **316 通过，0 失败**（初检 267；classifier 子任务交付后全套含其专项测试）。各一次运行，无重跑。
- `python3 -m compileall -q src/fstar tests` — 通过。
- 仓库无配置的 lint/typecheck 命令（spec 仍为待填模板），不声称未运行的检查。

## classifier 交付后的追加调整（协调者指派，2026-10-30）

`src/fstar/tool_classifier.py` 交付使三个交付前置守卫测试失效（ unavailable 路径在进程内不可达；伪造 ImportError fixture 输给 `fstar.__path__` 中的真实模块；子进程 smoke 不再非零）。本任务独占的 `tests/test_tools.py` 按协调者指示更新为兼容已交付 classifier，同时继续覆盖壳契约：

- `test_scan_handler_runs_before_project_discovery_and_reports_unavailable`：改用 `mock.patch.dict(sys.modules, {"fstar.tool_classifier": None})` 模拟真实模块缺失（import 机制的标准“缺失”标记，`ModuleNotFoundError.name` 即目标模块），断言壳在核心服务发现前分派并报稳定非零 `tools_classifier_unavailable`、非 `project_not_initialized`。
- `test_internal_import_failure_is_not_swallowed`：真实模块已缓存后，通过 `sys.meta_path` 注入 raising loader 模拟“模块存在但内部 ImportError”，断言 `tools_classifier_import_failed` 且不被当作空扫描吞掉；注入移除后真实 classifier 恢复可用。
- `test_cli_subprocess_smoke_on_uninitialized_directory`：改为正向——真实子进程在未 init 目录经 `python3 -m fstar` 返回 0 与有效 `fstar.tools.scan.v1`，且不创建任何 fstar 元数据或 tools.yaml。
- 新增 `test_cli_subprocess_reports_unavailable_when_module_is_genuinely_absent`：独立子进程内先标记模块缺失再导入 CLI，验证真实子进程级别的 unavailable 契约仍成立。
- 新增 `test_delivered_classifier_scan_runs_through_cli_on_uninitialized_directory`：正向路径——真实 classifier 经真实 `cli.main` 在未 init 目录返回合法 scan.v1（schema + 五键齐全），零绑定/零元数据副作用。

未触碰 `src/fstar/tool_classifier.py`（classifier checker 所有）。本轮后目标 80/全量 316/compileall 全部通过。

## package-install 交付后的追加调整（协调者指派，2026-10-30）

package-install 子任务经 `src/fstar/installer.py` 合法注册 install/update/uninstall/doctor/migrate/version（父 design §4.1 安装管理面），使 `test_parser_exposes_only_tools_scan` 中把 `install` 列为禁止命令的交付前置守卫过期。已更新为仅禁止真正不存在的新命令（`bind/status/validate/verify/reminder`），并注明安装器六命令是父授权的包管理面而非 tools 命令；`tools scan` 仍为 tools 模块唯一用户命令。仅改 `tests/test_tools.py` 本测试。本轮后目标 80 / 全量 489 / compileall 全部通过。

## fstar-tools SKILL 复核

描述 72 字符（≤200），12 条描述合计 888（≤2400）；单一绑定指导入口（指向 `../../references/tool-bindings.md`）；`fstar tools scan` 为唯一用户命令；`validate_resources` 零诊断。

## 留给后续所有者（非本任务缺陷）

- reference 示例中的 `validates` 占位 digest 与当前真实计算值不同，但文档已明确声明“digest 与确认必须由真实 proposal 与真实用户确认产生、本文件不声称发生过调用”，属被许可的示意值，未改动。
- 真实宿主内调用/扫描观察、classifier 全量实现、init 首次提案、knowledge/installer/runtime 消费接口均由对应子任务交付，本任务仅为协议与接口就绪。
