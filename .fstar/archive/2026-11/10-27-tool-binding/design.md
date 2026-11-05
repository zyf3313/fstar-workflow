# 工具绑定技术设计

## 1. 权威、读取与文件边界

完整读取父 `../10-25-fstar-workflow-design/{prd,design,implement}.md`；父 design 自动注入可能截断，必须 Read 补齐全文。父契约覆盖 research 的旧包数、code-text、turn-context 与 AI 判断例外。Python 3.9 标准库，`from __future__ import annotations`，Optional 等兼容类型。

实施独占：`src/fstar/tools.py`、`tests/test_tools.py`、`resources/capabilities/<五ID>.md`、`resources/schemas/tools.schema.json`、`resources/references/tool-bindings.md`（格式/API 单一说明，含示例）。现有 `resources/skills/fstar-tools/SKILL.md` 可在内容所有者交接后补绑定流程引用，保持唯一指导入口。默认推荐数据内置 tools 模块，installer 可随包分发；不创建用户绑定文件作为安装副作用。

`fstar.tools` 保留给绑定与唯一命令注册，可在不改导出 API 下拆 tools/ 包。后续 classifier 独占 `src/fstar/tool_classifier.py`、registry 及探针；不能占 tools.py 或重复注册。cli 已有 optional 列表 `("project", "runtime", "tools", "dispatch")`，无需改 cli/runtime/config/tasks/evidence。本轮只写五份规划文件，上述是后续实施范围。

## 2. 窄公共 API

以下为本任务交付的稳定接口，使用可 JSON 编码 dict，禁止暴露解析器私有函数：

| API | 输入与输出/副作用 |
|---|---|
| `load_tools(path: Path) -> dict` | 读单文件，返回 `{state: missing|loaded, path, document, digest}`；missing digest=null；存在文件解析/校验失败抛 DomainError，不返回空成功 |
| `validate_tools(document: dict) -> dict` | 纯 schema/跨字段检查，返回规范化副本，不修改调用方数据 |
| `resolve_bindings(*, project, user, defaults) -> dict` | 参数为上述加载结果及默认推荐，输出五能力的 resolution；无 IO |
| `build_binding_proposal(*, target, loaded, changes, reason) -> dict` | 纯生成精确变更、目标作用域/绝对路径、原文件 digest、proposal digest；不持久化 |
| `apply_binding(proposal, confirmation, *, clock) -> dict` | 内部 API；验证确认/并发后原子提交目标 tools.yaml，与授权/历史同一次提交；不改其他层 |
| `assess_availability(resolution, observations) -> dict` | 纯验证三层观察，缺事实层为 unknown，输出 gap；不调用宿主 |
| `build_provenance(resolution, call_record, availability) -> dict` | 仅真实调用形成记录；无调用身份/来源拒绝，不拿扫描记录充数 |
| `record_provenance(store, ref, record, *, lease_token, clock) -> dict` | 使用核心 TaskStore 事务/read/resolve/write；ref=None 则只返回 session_only、不碰 store |
| `register_commands(subparsers) -> None` | 唯一 tools/scan 注册，`_fstar_module_handler` 挂在 tools 父 parser 并继承到 scan |

classifier 的最小回调接口为 `scan_tools(*, project_root, user_root, host_snapshot) -> dict`，返回 `fstar.tools.scan.v1`：`detected_at/tools/observations/proposals/diagnostics`；复用本 schema 的 Tool 与 Observation，不直接写绑定。tools handler 延迟导入 `fstar.tool_classifier.scan_tools`；仅目标模块确实不存在时报 `tools_classifier_unavailable`，导入的内部故障不得当作空扫描吞掉。init 后续直接复用同一回调与 proposal API；knowledge 读取 knowledge-retrieval resolution，installer 分发五契约/schema 并保留用户数据。无新 bind/status/verify/install 用户命令。

## 3. tools.yaml v1 与实际解析子集

复用 **`config.parse_config(text, path)`**，不调用 `load_config`（后者强制 config 专用 schema/language），不复用私有 `_merge`。工具绑定按整条能力事项覆盖，通用配置递归合并会把不同工具的旧确认拼在一起，故本模块实现小型 schema 专用合并。

实际 parser 支持：顶层 mapping、两空格缩进的嵌套 mapping、标量、JSON flow list/object、标量块序列；**不支持 `- tool: x` 后续缩进属性的块映射序列**、多行 flow、锚点/tag/多文档/块字符串。复杂 tools/capabilities/history 数组使用单行 JSON flow，或每行 `- {"tool": ...}` 完整 JSON 对象。对象键须 `[A-Za-z_][A-Za-z0-9_-]*`；时间、版本、URL/原话作为字符串值，不作任意键。不要提供漂亮但实际不可解析的 YAML。写入器仅序列化本 schema：顶层键后单行 `json.dumps(value, ensure_ascii=False)`，不新建通用 YAML writer/parser；整文件 JSON 也不直接交给此 parser。

`fstar.tools.v1` 必需顶层：`schema, detected_at, tools, bindings, history`，未知字段拒绝。空文件不是 missing；缺 schema 明确报错。schema JSON 是分发契约，运行时用 stdlib 显式校验，不引第三方 jsonschema。

| 结构 | 字段与约束 |
|---|---|
| Tool | `tool` 非空稳定 ID（在文件内唯一）；`kind=cli|mcp|skill|builtin`；`version` 字符串或 null；`capabilities[]` |
| Match | `id` 五能力之一（同工具内唯一）；`match=strong|weak|none`；`basis` 非空说明；`basis_source={kind:registry|probe|user|unclassified, reference, confirmation?}` |
| Binding | bindings 的键为五能力 ID；值 `{tool: ID|null, reason, confirmation}`；整条覆盖，null tool 为显式不绑定。确认绑定可选 weak/none，但不得据此自动改其分类 |
| Confirmation | `source_id,type:command|conversation|review,at,actor:{role:user,id},reference,quote,scope,validates`；scope 为目标+精确 changes；validates 为 proposal digest |
| History | `{id,at,kind:binding_changed,changes,source,before_digest}`；source 完整确认；仅已提交绑定变更记录，不存提案授权 |

`detected_at` 为 ISO-8601 UTC 字符串或 null，描述已保存工具发现快照时间，不表示当前可用。tools 中允许保存分类快照，但 scan 默认只返回事实，不自动覆写配置。每个 binding 引用同文件 Tool（保证可移植及确认快照完整）；若用户文件覆盖工具元数据但未写该能力 binding，不改别层该项实际选定工具。选定 Binding 与其同层 Tool 作为一个来源快照解析，返回 origin/path/digest，防止拼接。

strong 仅接受 registry 引用或经过确认的 user basis；probe 只能 weak，unclassified 为 none。用户确认分类与确认选择是两个事实，前者必须明确包含能力判断，不从选择推断。任何 strong 都不代表三层验证通过。schema 禁止第六能力 code-text。

支持子集示例（示意来源与 digest 须由真实确认替换；不能直接当批准导入）：

```yaml
schema: fstar.tools.v1
detected_at: "2026-10-29T08:00:00Z"
tools:
  - {"tool":"codegraph","kind":"mcp","version":null,"capabilities":[{"id":"code-structure","match":"strong","basis":"符号定义/调用关系接口","basis_source":{"kind":"registry","reference":"registry/codegraph.yaml@v1"}}]}
bindings:
  code-structure: {"tool":"codegraph","reason":"用户选定结构检索","confirmation":{"source_id":"input-17","type":"conversation","at":"2026-10-29T08:05:00Z","actor":{"role":"user","id":"user-1"},"reference":"host/session-1/input-17","quote":"此项目用 codegraph 做结构检索","scope":{"target":"project","path":"/fixture/.fstar/tools.yaml","changes":{"code-structure":"codegraph"}},"validates":"<proposal-sha256>"}}
history: []
```

真实成功变更必须同时追加 history；示例说明形状，不声称发生过调用。fixture 测试先构造 proposal 再生成与它匹配的来源，完整提交后验证往返。

## 4. 解析、授权与持久化

每层先独立加载/校验，坏高层不被低层掩盖。遍历固定五 ID：项目含键取项目整条，否则用户，否则默认推荐。输出 resolution：`capability, state:bound|unbound|recommended, tool, match, origin, binding_digest, confirmation, recommendation`。显式 tool=null 为 unbound 且停止回退；缺键允许继承。默认只有推荐、无 confirmation，不得标 bound。读取历史配置时保留历史确认，不拿当前整文件 digest 去要求历史签名匹配当前文件；新 mutation 则必须绑定当前 proposal。

proposal 包含 canonical target（user/project）、允许根内目标路径、原始字节 SHA-256（缺文件为 null）、changes、reason。changes 值为工具 ID 或 null；新增工具快照也包含在 proposal 中，确认覆盖完整 diff。proposal digest 用核心 `content_hash`（排序 JSON SHA-256），确认 `scope` 必须与 proposal 的 target/path/changes 相等，`validates` 等于其 digest。conversation 必须有原话与可定位引用；command 必须是用户来源；review 必须由调用方提供能回链真实当前用户确认的记录，只有文件 approved 字样拒绝。不得直接调用 `tasks.validate_source` 假造 task：该函数的哈希是 task snapshot，与绑定 proposal 不同；只沿用来源字段/可信边界。

写入顺序：纯校验与生成候选内容→锁住目标对应的用户 runtime 锁→重读原内容及 digest→确认快照未变→序列化并回解析校验→同目录临时文件/fsync/os.replace→返回成功。确认记录和 binding/history 同文件原子提交，不另写授权台账；冲突/写失败保持原文件及其历史不变，清理临时文件。锁并发使用标准库 fcntl，沿当前 POSIX 基线，明确可移植性限制。拒绝路径越界/符号链接替换；显式用户根与项目根由调用方传入，测试绝不使用真实 HOME。确认前不创建目标目录/锁文件；读/提案不落盘。新项目级绑定须项目已接入，用户级绑定不隐式 init。

错误统一 DomainError(code,message,details,status)，保留 parser 的 path/line/key 与原 code；如 `tools_invalid_schema/tools_read_error/tools_encoding_error/tools_binding_conflict/tools_confirmation_required/tools_stale_confirmation/tools_invalid_observation`。缺配置是返回 missing；明确要求的坏配置是非零错误；授权拒绝 status=3、并发/租约冲突=4，格式错误=2。不靠宽泛 except 把失败变缺失。

## 5. 三层观察、缺口及宿主边界

Observation：`tool,capability,layer:discoverable|client_loaded|minimal_call,status:verified|failed|unknown,at,scope:{project,host,session},evidence_ref,reason,call_id?`。verified 必有可核验 evidence_ref；failed 必有 reason；unknown 说明未观察/无适配能力。minimal_call verified 必须关联真实 call_id。不同工具、会话或项目的观察不能拼成当前三层全通过；旧观察保留但当前报告标 unknown/stale，时效由调用方显式传入，不在解析时隐藏刷新。扫描/验证数据都不自动把 match 提升。

宿主适配器在宿主内列工具/读取客户端状态/发起已允许的最小真实调用，将带来源结果交给本模块。无适配器只能报告可确认的本地存在性，其余 unknown；不能从 MCP 配置推断已加载、从 skill 文件推断已执行。规划及本任务确定性测试不联网、不运行未知工具或安装；真实调用验证由 classifier/e2e 在具体上下文按授权执行。

五契约的验证与降级边界：

| 能力 | 可判定/最小真实调用 | 降级 |
|---|---|---|
| code-structure | 已知符号定义/引用可追文件行，区分不存在与未索引；查询一个已知符号 | 字面搜索仅定位文本，不能声称调用图/影响面已验证 |
| web-research | 原始来源可读取、版本/出处可追；读取用户任务所需的单一已知来源 | 本地资料/已有缓存，明确日期与无法核实最新版本 |
| knowledge-retrieval | 集合新鲜度、关键词/语义路线与来源路径可检查；查询已知本地文档 | 索引/文本查询，缺语义或新鲜度时逐项说明 |
| data-access | 可证连接、只读权限与 schema/查询边界；经授权只读会话最小查询 | 只读导出/schema 文档，明确非实时；不执行写 SQL |
| test-execution | 命令、退出码、可定位失败与环境可记录；隔离 fixture 中一个已知测试 | 静态检查与未运行标识，不能算测试通过 |

不把运行任意项目测试视为无副作用探针；宿主确认适用范围后选择隔离 fixture。缺口 `capability/tool/origin/match/missing_layers/reasons/recommendations{source}/fallback` 返回调用方，是否阻断由实际任务要求决定，不写 task blocked/acceptance。建议是来源引用，不下载或执行安装命令。

## 6. provenance 被核心消费的具体边界

`fstar.tool-use.v1` 记录：`id,capability,tool,kind,version,at,binding_origin,binding_digest,match,basis,call:{id,reference,operation,result},availability,fallback`。operation 是脱敏操作摘要，result=passed|failed|blocked；只记录已尝试且有实际调用来源的事实。未调用的 unknown/gap 只留报告，不插 capabilities；不存凭据、SQL 数据或原始敏感响应。缺版本用 null，不编造。

实际核心 `TaskService` 尚无 record_capability API，`EvidenceService.record` 只添加 evidence，**不会**把自定义字段复制进 capabilities。本任务因此交付 `tools.record_provenance` 薄桥接：`with store.transaction()` 后 `store.resolve(ref)`、`store.read(ref)`；校验 active/in_progress、未 dropped、有效 lease_token 与 expires_at，记录 ID 重放相同内容则幂等返回、不同内容拒绝；追加 capabilities 与统一事件封套（复用 tasks.make_event/compact_events），经 `store.write` 的 validate_task/原子 IO 提交。这里使用现有核心公共存储边界，不直接 json.dump task，不调用私有 `_write`、不新增 core API 或 task 顶层字段。租约不因单纯工具日志自行续时，worker 回报续租仍由核心原路径负责。

这条桥接必须用真实 TaskStore 临时项目测试，确认保存到 capabilities、events，extensions/phase/acceptance 不变。独立 check 证据仍走 EvidenceService，provenance 不生成 check pass。ref=None 提前返回 `{persistence:session_only,record}`，不得实例化写事务或创建 runtime。runtime 后续若消费此 payload 由其所有者独立集成；本任务不改 dispatch/result schema。

## 7. 集成与风险

classifier 依赖本 schema/API 完成后才实现全量扫描；本任务 scan 壳在缺该模块时明确非零未就绪，不能把这项后续集成算已完成。init 首次扫描只提案、工具包未启用也能接入；knowledge 按需解析检索能力，不把 knowledge 条目当绑定；installer 管资源分发与 registry.d 路径，升级不覆盖用户已确认绑定。session 轻检查由 runtime 所有者后续接入，只查存在性/过期，不拉全量扫描。

测试覆盖 YAML 实际子集、整条覆盖、unknown、来源边界和并发提交。回滚代码/资源不自动回滚用户配置；无须重批产品范围。
