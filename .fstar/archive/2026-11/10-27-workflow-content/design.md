# 工作流内容设计

## 1. 权威、边界与实现默认

父 `../10-25-fstar-workflow-design/{prd,design,implement}.md` 为当前依据，尤其 design §2.4、§3.7–3.12、§4。父 design 必须完整 Read；注入截断时补读全部遗漏部分后才执行。研究稿中的旧“doc 写 plan”等描述不覆盖父设计：plan 自己维护 plan.md。

本轮只准备五个规划文件。未来实现 Python 3.9 标准库，类型使用 Optional/Mapping/Sequence，不增加 YAML 第三方依赖。资源文本与纯校验集中在本任务；状态/哈希、配置/接入 IO、宿主桥接、知识事务和安装分别归其所有者。内容回滚只替换安装默认资产，不改用户模板、任务正文或知识。

## 2. 精确资源清单

以下均为源码路径，发布逻辑路径去掉 `resources/`，实际安装定位由 package-install 处理，不硬编码 site-packages、cwd 或用户 home。

| 路径 | 内容 |
|---|---|
| `resources/skills/fstar-<name>/SKILL.md` | 12 个 name：init、clarify、doc、plan、execute、check、continue、archive、learn、debug、help、tools |
| `resources/agents/fstar-<role>.md` | 4 个 role：research、implement、check、editor |
| `resources/runtime/routing.md` | 安装包唯一调用前路由，v1 无项目/用户覆盖 |
| `resources/templates/doc/{prd,design}.md` | 2 个评审正文模板 |
| `resources/templates/task/{plan,clarify,research,check}.md` | 4 个任务模板 |
| `resources/templates/knowledge/{rule,memory,spec}.md` | 3 个知识模板 |
| `resources/templates/entry/{user-index,project-index}.md` | 2 个入口模板 |
| `resources/templates/doc/{prd,design}.mapping.yaml` | 语义槽位、ID/关联提取定义 |
| `resources/templates/task/plan.mapping.yaml` | 计划项 ID、来源/依赖提取定义，供 core 同一 artifact_map 消费 |
| `resources/references/knowledge-format.md` | 唯一知识格式说明 |
| `resources/references/document-checklist.md` | doc/editor 回读与 check 独立一致性检查共用清单 |
| `resources/references/technical-design-profiles.md` | 固定来源 profiles 及章节引用适配；按需读，不是模板 |
| `src/fstar/content.py`、`tests/test_content.py` | 只读内容校验/提取 API 与对应测试 |

不另建 workflow.md 路由副本或入口索引；help 消费 package-install 生成的实际入口信息。测试 fixture 使用临时目录和测试内字符串，必要时再拆小 fixture，不能把示例算成第十二个模板。

### Skill 内容合同

SKILL.md 必填 name/description，name 匹配目录；正文英文为主，description 中英双语、每条≤200字符/总计≤2400（不含名称/分隔成本，不是 token）。宿主字段/入口由安装器适配，不为省预算禁用自动路由。

| Skill | 路由与必要步骤 |
|---|---|
| execute | 核心自动。核对授权/有效 plan 或会话目标→通过原生工具派 implement→按依赖及文件范围协调→交独立 check→用户确认。主 Agent 单写 plan 进度/协调任务，worker 不写 task.json；无 inline 回退。 |
| check | 核心自动。固定范围/基线/结束条件；独立文档检查或代码检查，补测试/运行/本范围自修；按影响复查+最终整体检查，五态、真实耗时/重跑、阻塞返回。需求/预期变化回 clarify。 |
| debug | 核心自动。保留失败证据、找根因、限定修复与复查；派发第二次失败（最多自动重试1次）或无进展进入此处。 |
| help | 核心自动。读安装入口索引/实际配置，只读解释已安装功能与缺项。 |
| plan | 评审确认后自动。核对当前正文/研究/规范/相关代码与测试，生成/局部刷新 plan.md；有效无阻塞后 execute，无额外批准。 |
| init | 按授权。全项目事实探索→缺背景才问→主题/权威引用→ProjectContext→初始化→核验导航；已有索引保留后按明确修改范围维护；工具扫描/绑定独立授权。 |
| clarify | 按授权。证据优先、按决策依赖讨论，自行维护 clarify.md；简单事实记来源，多源比较/协议/探测/取舍进 research；只传递明确结论。 |
| doc | 按授权。只管 doc/；每次写作派后台 editor，携来源、讨论修订、当前哈希、指定条目/文件；排队/收齐/回读→独立一致性 check→用户评审。已批准未变范围同步不再审批。 |
| continue | 按授权。当前任务只读核实版本/遗留产物/worker/租约，按已有授权推进；孤儿由用户决定接管/重派/放弃。无归档巡检/历史总览。 |
| archive | 按授权。核验用户验收/新鲜证据/子树/未决→衔接可选 learn→core 整树归档→展示其他长期未归档候选及依据/缺项/暂缓去重。不自动归档其他任务。 |
| learn | 按授权。候选内容/来源/归属/冲突→已授权直接写，否则先确认→先归已有主题→正文/索引/引用整组更新并核验。忙时/复杂时用通用后台 Agent，小改可直接处理。 |
| tools | 按授权。消费五能力的绑定/三层验证/指引/实际调用记录/缺口降级；不自动安装或改绑定，不将工具可用视为验收通过。 |

### Role 内容合同

角色卡包含 name/description、输入、allowed_paths、必要上下文、工作/回报规则，不复制整套 skill 流程。research 绑定调用方研究目标和 research 模板，没有 research skill；implement 消费 execute 派发；check 消费 check；editor 消费 doc。

派发字段对齐父 design §3.7：dispatch_id、task_ref、role、plan_item_ids、baseline、输入版本/指纹、allowed_paths、read_context、必需验证和返回条件；持久任务提示首行为 `Active task: <path>`，无任务为 `Active task: session-only`。返回身份、status、changed_paths、产物引用、验证事实、耗时/重跑、阻塞及基线；原生适配器承担真正派发/回收，文本不能假称已经启动。

- research 只在指定 research 范围落依据、来源、结论和限制，不写生产代码/状态。
- implement 写指定产品/测试范围，完成小步自检并交付，不能把自检冒充独立 check；接到交接即停止该范围写入。
- check 独立于 implement producer，允许本范围生产/测试自修，不改需求/批准/预期来消除失败；无需递归派新 checker。文档检查发现需求歧义回报，已明确的 doc 修改仍走 doc/editor。
- editor 仅改指定 doc 文件/条目；不自行新增/删除 ID、不裁决需求/批准；缺信息回报。提交前比较基础哈希，冲突不覆盖，交主 Agent 合并/重派；回读槽位/ID/关联/图文并返回改动/未决。宿主权限能力由 runtime 实测，角色卡不是安全沙箱。

## 3. Routing 与产物责任

routing 只写触发条件、授权判断和下一 skill，不复制 CLI 状态校验或 skill 全流程。核心顺序为会话 clarifying→executing→checking↔fixing→awaiting_user；这些不是落盘 phase。持久任务仅 planning/in_progress/completed，最终 accept/归档均交 core。

五个 package IDs 与具名能力取父 design §2.4 的包清单。未启用包时先说明收益/代价，一次推荐最高价值一个，full/custom 不能裁三底线；拒绝后无新事实不重问。授权互不暗含；规划评审可建授权文件而不创建 task.json；持久化中途启用从 planning 导入有效成果，不重做。基础 implement/check 原生分离始终可用。

回忆意图查询 knowledge 与 `task list --archived`，返回来源及适用差异，不自动恢复归档任务。archive-only 巡检：默认30天/暂缓7天由 core 配置消费，显示时间依据和技术默认属性；session/continue/check 不发归档催办。learn 候选可在现有会话/回收/恢复/归档节点识别，不增 hook/独立候选台账。

最小闭环无 fstar 元数据；会话结果直接回报。获准持久化时检查报告写 `acceptance/check-<n>.md`，clarify/plan 位于任务根，doc 仅 prd/design，research 只在依据需要时建。独立 planning-review 无持久任务时路径由授权的产物根指定，内容 API 不自动拼 `.fstar/tasks/`。

模板内容要求：plan 保持 Summary/Patterns to Mirror/Files to Change/Tasks/Validation/Risks/Acceptance 七段；项有 ID/来源/依赖/优先级/并行条件/完成判据，每组有测试/文档责任。check 报告显示 requirement/design/plan→test path/identifier→command/result/log，scope=incremental|final、环境/run id/交付基线/未覆盖项/修复/实测耗时；结果机器值 passed/failed/blocked/skipped/not_run。没有用例审批前置。

## 4. 模板映射与 core 交接

### 4.1 来源、解析与占位符

prd/design/profiles 从 `zyf3313/fstar-trellis-ext` 提交 `674bea37cf2f6f25cd20dab93e1a54ae1f13ce66` 获取并核对实际许可/来源，保留来源注释；本轮不下载/复制。按 personal-template-review 调整产品路径、profiles 引用、design 7/8/9 章节，保留逐功能技术设计与 PRD AC，不添加独立测试文档。

占位符统一 `{{snake_case_name}}`，模板注释声明允许/必需集合；渲染后不得遗留必需占位，示例须替换，未知事实列待确认。程序不判断自然语言完整性。

mapping.yaml 采用 UTF-8 **JSON 对象语法的 YAML 子集**，标准 json 读取，不复用 config 私有 parser。拒绝重复键、NaN/Infinity、未知版本及可执行表达式，明确报支持的语法。

template+mapping 成对按任务>项目>用户>默认选取，选中层坏映射报错、不静默降级。调用方/安装器提供资源版本与路径；本模块不联网或写配置。

### 4.2 默认标记及映射形状

doc 默认六个槽位分别使用唯一标记，例如 `<!-- fstar:slot:artifact_type:start -->prd<!-- fstar:slot:artifact_type:end -->`；同理 version/review_state/author/date/reviewer。reviewer 槽位必须存在，尚未评审可为空；其他槽位不能为空。review_state 保留实际文本且非授权证明，不能从槽位推断 core acceptance。

默认条目使用独占行，正文包含 ID、规则、AC/图示文字及显式关联：

```markdown
<!-- fstar:item:R-001:start -->
### R-001 示例需求
正文及验收条件……
<!-- fstar:ref:doc/design.md#D-001 -->
<!-- fstar:item:R-001:end -->
```

映射版本采用 `fstar.template-map.v1`，定义 artifact_type、slots、items 和 references；示意结构（具体 JSON 资源使用实际值）：

```json
{
  "schema": "fstar.template-map.v1",
  "artifact_type": "prd",
  "slots": {"artifact_type": {"start_marker": "<!-- fstar:slot:artifact_type:start -->", "end_marker": "<!-- fstar:slot:artifact_type:end -->"}},
  "items": {"mode": "markers", "start_template": "<!-- fstar:item:{id}:start -->", "end_template": "<!-- fstar:item:{id}:end -->"},
  "references": {"prefix": "<!-- fstar:ref:", "suffix": " -->", "separator": "#"}
}
```

实际 doc 映射 slots 必须恰好覆盖六个必需语义名；plan 映射只需它自己的 artifact_type/版本信息及条目/来源关联，不向所有11模板强塞评审槽位。默认 markers 模式通过 start_template 的固定前后缀提取 ID，要求非空、无换行/控制字符/分隔符冲突，end_template 以同一 ID 展开；不绑定 R/D/P 前缀或标题语言。每个 ID 仅一对、end 在 start 后、区间不重叠不嵌套；边界字符串在全文出现恰好一次，防止示例或重复片段冒充条目。

自定义 `items.mode=explicit` 接受 `entries:[{id,start_marker,end_marker}]`，适配任意唯一文字/锚点和 ID 写法；没有可唯一定位的边界就要求补映射，不按标题层级猜正文终点。slots 同样可换字面边界。关联默认从条目内 reference 注释提取 artifact#id；自定义可提供 `references.mode=explicit` 的条目关系清单，保持来源项/目标项明确，不解析自然语言链接来猜依赖。

关联目标规范化为相对**授权产物根**路径及 ID；交 core 时转换成相对**项目根**的 artifact。拒绝绝对路径、路径穿越、越界 symlink，关联文件/ID 缺失、重复/歧义均诊断。允许尚未完成的规划映射作为诊断结果展示，但不可当成有效检查/批准快照。explicit whole-file 模式仅在调用方明确选择时输出 granularity=file，不伪造条目 ID 或宣称精确失效。

### 4.3 唯一 artifact_map 与哈希所有权

`extract_artifact` 结果含 artifact、slots、items（每项 id/start_marker/end_marker/references）、granularity、diagnostics，不含条目哈希。映射中关联依赖方向按明确声明传递，不能认为所有链接天然双向依赖。

`build_artifact_map` 将成功提取的条目转成 core design §5.1 要求的 artifact→稳定 ID→唯一 start_marker/end_marker，并附显式依赖；保存位置仅在 **`task.json.meta.templates` 的对应映射记录内的 `artifact_map`**。模板 source/ref/hash 与映射同一记录绑定，不新增顶层字段或平行 meta 字段。无 task.json 时交接对象留在当前调用/授权产物上下文，不私建状态库。

持久化封装、来源记录和事务由 core/runtime 完成，content 不直接写 task.json。core 的 `EvidenceService.snapshot(ref, artifact=..., items=...)` 按这些原始标记提取**边界之间全部正文**，统一 CRLF→LF 后 UTF-8 SHA-256；content 不 trim/改写正文或独立哈希。边界是否含末尾换行以 core 实际实现为唯一准绳，集成 fixture 锁定，不能两边各选一套规范化。模板/映射资源 hash 由安装器或 core 资源 provenance 计算，区别于条目哈希。

正文、ID、映射、依赖或交付代码/测试/共享配置变动交 core 重新核对。映射换版不能静默扩大/缩小旧证据覆盖；旧证据 stale 保留，新证据重生。core 映射 API 若尚未固定序列化外壳，消费侧只做窄适配，不发明第二套持久格式。

## 5. 知识、索引与项目接口

knowledge-format 是唯一完整格式参考，三模板/init/learn 引用它而不复制整份规则。frontmatter 用简单标量字段：schema=fstar.knowledge.v1、type=rule|memory|spec、status=active|superseded；rule 有 strength=enforced|default；memory 有 kind=preference|lesson 与 trust=confirmed|unreviewed。缺失/非法值报错。知识加载器由 knowledge-base 实现：过滤 superseded/unreviewed 后按适用范围和 enforced>项目spec>default>confirmed memory 裁决；不将格式验证当语义适用判断。

rule 正文短断言 MUST/NEVER/APPLIES/NOT/SOURCE；memory 内容+APPLIES/NOT/SOURCE；spec 简明可执行、有依据、必要短示例，不强加多栏目。rules/memory 英文；spec 用 `language.specs`；context/references 按项目产物语言，不套知识 frontmatter。长期决定归 specs，仅 knowledge/context 与 references；不建 history/journal/decisions。

init skill 消费 `load_config(project_root,user_root)` 的 values/origins；形成 `ProjectContext(project_summary,topics,authority_refs,knowledge_refs)` 传 `initialize_project(path,user_root,context=...,dry_run=...)`。TopicReference 对齐 id/title/applies_to/read_when/path，DocumentReference 为 title/path；引用需真实存在，尚未落盘的建议不塞成有效链接。用户接入用 initialize_user。已有索引保持时尊重 context_complete/warnings，不能声称新 context 已写入。

entry 模板：user-index 列规则主题/强制性/路径、记忆主题/kind/路径、本地定制；project-index 列概况、主题/Applies to/读取条件/权威路径、长期知识和已有权威资料优先声明。索引只导航，缺目录不渲染假链接。project-layout 的基础兜底可在没有本资源时初始化，正式模板不能反向阻塞它。

learn 先查主题/正文去重，现有明确内容与归属授权直接使用；同文件单写，正文/索引/引用由 knowledge-base 事务 API 暂存校验后提交，失败恢复。该 API 尚未交付时不得把普通逐文件写入声称原子成功。

## 6. 内容 API 与校验分工

计划公开接口仅在 `src/fstar/content.py`，无模块导入写盘、副作用、print/exit 或新增 CLI：

```python
validate_resources(resource_root: Path) -> Sequence[Diagnostic]
load_mapping(path: Path) -> Mapping[str, object]
extract_artifact(text: str, mapping: Mapping[str, object], *, artifact: str) -> Extraction
build_artifact_map(extractions: Sequence[Extraction]) -> Mapping[str, object]
validate_links(resource_root: Path, paths: Sequence[Path]) -> Sequence[Diagnostic]
```

Diagnostic 至少 code/path/line/message；Extraction 为只读结果，含 §4.3 字段及 ok。load_mapping 格式错误抛 ContentError(code/path/line/message)；extract 累积可定位诊断，build 遇 invalid 拒绝生成可消费 map。API 只接受调用方显式根/路径；跨文件引用由传入的 extraction 集合解析。安装器/doctor 调 validate_resources，runtime/核心接入方调 load/extract/build，project/knowledge 用模板与格式参考。适配 core 的实际 dict 形状集中在 build，不复制 EvidenceService。

机器校验：严格资源集合/命名、frontmatter 必填、描述计数、占位符、必需槽位、标记/ID/关联、资源引用与路径、版本/重复键/非法映射、纯读无写入。frontmatter 解析公开限定简单 scalar 子集，不宣称支持完整 YAML，不导入 project 的私有 parser。知识运行时 schema 验证由 knowledge-base 所有；content 先校验内置模板的结构/示例，未来集成必须调用同一权威 validator，不能长期分叉。

语义检查：routing 授权、角色分离、文档/计划职责、check 自修与五态、init/learn、来源/章节/语言、图文一致性/条件完整性，由独立 check 对 PRD AC 与共享 checklist 审查。关键词出现或测试里的字符串相等不能证明工作流真的正确。两宿主实际派发/事件/listing/后台行为由 runtime 与 e2e 给真实证据。

## 7. 所有权、待交付接口与风险

| 所有者 | 精确交接与待验证条件 |
|---|---|
| workflow-content | 独占 §2 列出的资源、content.py、test_content.py；提供 marker 映射/诊断 API、格式参考与模板，不改其他模块。 |
| core-commands | 独占 models/store/tasks/evidence/cli；消费 meta.templates 中 artifact_map，负责 SHA-256/新鲜度/事务/确认。需在实现交接时锁定外壳和 dependencies 形状，并跑同一 marker fixture；本设计不抢写 core。 |
| project-layout | 独占 project.py/config.py；已给 ProjectContext/init/load_config 接口，需核对实际类型及 entry 模板渲染接点；不要求基础 init 依赖安装资源。 |
| runtime-hooks / dispatch | 四 hooks 注入完整上下文；原生工具执行后台 editor/implement/check/research，校验基线/范围和回收；需双宿主实测，不由角色文本保证。 |
| knowledge-base | 权威知识 schema/过滤/冲突及原子正文+索引+引用 API，需落实后集成 learn 与模板校验，不能 content 自造后端。 |
| package-install | resources→逻辑资源路径、固定资源版本解析、source/hash、入口索引、doctor 调用；需交付实际 resolver，content 不决定安装目录/宿主 frontmatter。 |
| tool-binding / classifier | 五能力/绑定/扫描 API，init/tools 只消费实际接口；未交付时报告限制，不假称扫描成功。 |
| e2e-verify | 完整授权/两宿主路由/并行/更新保护与最终用户验收证据。 |

上列为技术交付依赖，不是待批准产品决定。源码模板尚须按固定提交读取实际全文并核对许可；引用研究摘要不能冒充模板已落地。父设计优先于三份研究中的历史措辞。超出所有权的接口改变先与对应实现协调，父 scope 不变无需重开批准。
