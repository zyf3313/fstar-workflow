# 设计并实现个人工作流系统 fstar-workflow

## Goal

参考 Trellis 的完整闭环体验，设计并实现个人跨项目工作流系统。fstar 独立实现任务层、协议、适配器及数据格式，不依赖 Trellis 安装，不 fork 或复制其源码。发布形态为 Node CLI + Python 脚本的可安装包，命令名 `fstar`（发布前核实名称冲突）。

**当前授权**：用户已批准最终规划总结并明确授权第一版全部十个子任务实施。本文、`design.md`、`implement.md` 是当前执行依据；历史决定与替代原因查 `research/policy-decisions.md`，历史研究稿与 `docs/project-context.md` 不覆盖本文的当前规则。子任务旧文档按用户决定在各自开工时刷新；已批准范围不重新索取批准。本次父文档收敛不代表已运行 task start 或完成实现。

## 用户背景与定位

用户长期使用 Trellis，希望保留澄清、按需设计、子 Agent 实施、独立检查与修复、知识沉淀、恢复和归档的完整体验，同时让公共能力装一次即可跨项目使用。当前项目使用 Trellis 管理开发，不决定产品依赖关系。

用户级 `~/.fstar/` 保存个人规则、记忆、工具绑定与定制入口；项目级 `.fstar/` 保存项目规范、知识与嵌套任务树；安装包保存程序和默认资源。目录按需创建，已有权威文档优先引用。宿主资源安装到用户级，项目级只保存数据。

## 必须保留的体验（用户明确表达）

1. 适时进入澄清、调研、设计、实施、检查、沉淀和归档，按实际需要加载上下文与产物。
2. 主 Agent 继续沟通与协调，生产代码实施全部交原生子 Agent；独立 check 承接检查。
3. 用户的中途补充与文件变更均能传导给受影响执行者，旧版本结果不能证明新版本正确。
4. 检查失败进入修复与复查；check 可直接修复任务范围内的生产代码与测试代码。
5. 最终完成由用户确认，不能从 worker 完成、文档已生成或命令成功推断用户验收。
6. 按目录识别主子任务，恢复时核实真实状态，整项需求最终做整体检查和归档。
7. 经验有明确内容与归属授权后进入知识；不为每次任务强行生成规则。

## 命名与沉淀目录

产品与仓库名 `fstar-workflow`。产品任务内使用 `clarify.md`、`plan.md`、`doc/prd.md`、按需 `doc/design.md`、`research/`、`acceptance/`、`subtasks/`。本项目 Trellis 父任务的实施计划仍叫 `implement.md`，不能据此生成产品任务的同名文件。

项目知识仅为 `knowledge/context/` 与 `knowledge/references/`；长期决定及原因归对应 `specs/`，任务取舍归 design/research。不建立独立 decisions、history、journal 或 workspace。用户 `rules/` 与 `memory/` 分开维护。

## 当前决策与授权边界

- 第一版一次性交付十个子任务，P0/P1 表示执行优先级，均在实施授权内。
- v1 支持 Claude Code 与 Codex，协议自研，传输使用宿主原生子 Agent；无工作流层 inline/subagent 开关。
- 项目规范优先于默认全局规则，默认规则优先于记忆；明确 `enforced` 的全局规则优先于项目规范。冲突须说明，不静默合并；宿主系统约束与用户当前明确指令仍优先。
- 状态只由命令校验后写入。命令核验来源与指纹，但不能把同一操作系统权限下的 CLI/JSON 当作能阻止 shell Agent 伪造批准的安全隔离，详见设计 §3.4。
- 第三方工具/skills 保持外部资源，发现、引用与绑定不等于收编或安装。绑定变更和工具安装不被扩展包授权自动代替。
- 用户规则、记忆、规范、任务和归档属于用户数据；安装、更新、卸载不静默覆盖或删除。
- `.trellis/` 已决定纳入版本控制。产品项目 specs/knowledge 纳入版本控制；本机配置和 runtime 排除。宿主生成文件按已确认的可复现策略及现有 ignore 规则处理，不强改用户配置。自动 git commit 默认关闭。

## 自研增量范围

### 1. 主任务内含子任务的目录组织

一个完整需求对应一个主任务，子任务置于内部 `subtasks/`，JSON 保存稳定标识、子目录引用与状态。小任务可不拆分；叶子负责自身实施检查，容器负责规划、协调与整体验收。父子关系不表示实施依赖；依赖写入子任务 PRD 与执行计划，由主 Agent 协调，无自动依赖调度器。

主任务整体归档，子任务完成后保留在原树中。归档任务有关的新需求或缺陷修复新建任务并引用历史任务，不将旧任务搬回活动目录；历史关联不自动成为父子关系或依赖。

### 2. 任务生命周期状态机

持久任务包采用三个正常状态：`planning → in_progress → completed`。实施、检查、修复均处于 `in_progress`；“待验收”是新鲜 check 通过、无在途租约时的派生显示。归档是 `fstar archive` 命令，移动目录并记录 `archivedAt`，不是 phase。

- `fstar start` 核实启动授权、当前规划依据和阻塞条件，进入 `in_progress`；规划文档评审确认即放行，自动 plan 后无需额外计划批准。
- `fstar accept` 必须核实独立 check 的新鲜通过证据、当前交付版本、用户确认来源、子任务条件和未决问题后，写 `completed` 与 `completedAt`。
- `blocked` 是属性；设置/解除要有来源。Agent 不自行写入再自行解除阻塞，用户所设阻塞由用户解除。
- `dropped` 是用户授权的遗弃戳，不是第四个正常 phase；须记录原因及保留现场/丢弃现场/转知识选择，可按用户决定复活到 planning。
- 根本需求/设计改变回 planning，记录原因、使已有证据 stale 并释放租约；一般检查失败或用户要求“改改”留在 in_progress。
- 证据按稳定条目 ID 和交付版本失效；当前完成依据过期时有效状态回 in_progress，历史验收与报告保留。
- 容器进度由子节点最靠前非终态推导，子节点全部 completed/dropped 才具备整体验收资格；不能只凭子任务完成推断容器完成。
- 同一任务单写者租约，默认 30 分钟，worker 每次有效回报续约 30 分钟。跨会话孤儿租约由 continue 只读核实并请用户决定接管、重派或放弃，不假装原 worker 存活。

字段、命令及固定限额见 `design.md` §4；经核对最新政策的完整清单，`task.json` 为 **26 个顶层字段**，早期 23 是误计数。

### 3. 归档提醒

巡检提醒只属于 `fstar-archive`。本次归档完成后，汇总当前项目其他长期未归档任务的名称、可核实时间依据、状态与缺失步骤，区分已完成未归档与仍缺检查/验收的停滞任务。支持统一暂缓与去重，不打断、不阻塞本次归档、不自动归档其他任务。continue、会话启动与每轮 hook 不做归档巡检。

归档前核实验收、证据、子任务及未决问题，并衔接 learn；用户暂缓/拒绝可选知识候选不阻塞归档。候选揭示的正确性问题仍是任务问题，不能作为可选沉淀略过。

### 4. 全局个人记忆

rules 保存明确约束，memory 保存偏好和经验；记忆转规则须有明确授权。支持修正、替换、删除及来源追踪，不把项目特例升级为全局规则。

learn 的候选触发包括用户要求记住、纠正、讨论形成长期约定、开发可复用发现、排障根因/check 重复问题、旧知识冲突、任务收尾及恢复相关未处理候选。过程中识别、合适节点集中呈现；明确要求记住时当场处理。展示拟保存内容、来源、归属建议及冲突；内容和归属已明确授权就直接保存，不再重复询问。

主 Agent 忙时交后台通用子 Agent；空闲且小改可直接执行，复杂去重/多文件整理优先后台。同一知识文件写入排队或合并；实际写入正文、索引和引用成功后才报告已记录。无新 learn 角色，无独立候选台账；未确认内容不进入生效知识，拒绝/暂缓不反复催促。

### 5. 能力契约 + 工具绑定 + 分类器

五个能力维度固定为 `code-structure`、`web-research`、`knowledge-retrieval`、`data-access`、`test-execution`。契约归 fstar，选择绑定归用户，工具是外部事实。每份契约含定义、可判定要点、三层验证、推荐实现、不合格实现、降级与记录要求。

Python 确定性分类：L1 探测 PATH/MCP/已装 skills，L2 依次使用声明式注册表、维度通用探针、未分类候选手动绑定。AI 不进入分类路径；通用探针命中一律 weak，注册表或用户确认才可 strong。可用性按可发现、客户端加载、最小真实调用三层验证。

init 首次探测与匹配后提出绑定建议，用户确认后才写 tools.yaml；工具能力包未启用也可完成项目接入。会话启动只检查存在性和探测过期；全量扫描仅 init 或显式 tools scan。日常需要具体维度时由调用方进入 fstar-tools：查绑定→验证→按需加载指引→调用与记录→缺口降级，不自动安装或换绑定。最小闭环可使用宿主已有工具，UI 工具按需使用不新增第六个核心契约。详见 `research/tools-capabilities.md`。

### 6. 项目长期知识库

`specs/` 记录必须如何做及理由；`knowledge/context/` 记录领域事实、术语、FAQ；`knowledge/references/` 记录外部资料与来源；历史任务事实保存在归档树。

“项目做过什么”由 `fstar task list --archived` 从归档 task.json、plan、commit 和目录现算现印日期、任务、结果、验收、详情链接，不另建历史台账。跨任务回忆是主路由意图，查询知识与归档后说明来源及适用差异，不自动恢复旧任务；continue 只管当前任务恢复推进。

项目知识属于项目治理包，要求项目已 init。长期资料不随任务归档消失，保存同样遵循 learn 的授权、去重和索引规则。

### 7. 规范按主题归口

init 检索项目类型、技术栈、模块及已有权威文档，规划主题职责与读取索引，不只处理眼前任务所在模块。零起步且依据不足时了解目标、技术栈与关键约束，复用已知答案，不将未定选型写成规范。完成后核验入口、主题、引用与背景来源；已有资料优先读取引用，改动已有内容须说明范围并获得相应授权。

每个主题记录标识、适用范围、权威路径或章节、读取条件。learn 先查索引与候选正文，优先更新已有主题，无归属才提议新增/调整并说明理由；跨模块规则保留一处正文、多处引用。主题可拆目录，不以文件数上限治理。

阅读先掌握项目概况、完整规范总索引及全局约束，再完整读取所有适用主题与上下游/共享契约；范围不明确扩大读取，新增依赖补读。索引或摘要不能替代适用正文。

写作参考 Trellis 已有沉淀方法：证据明确、规则简洁可执行、必要理由与短示例、先去重再更新索引。不新增多栏目固定正文骨架；压缩不能丢必要条件、例外和错误语义。脚本检查结构与引用，Agent 辅助语义重复/冲突判断，不宣称全自动语义治理。

### 8. 同一事实源，多种阅读视图

prd/design 是人机共用的权威评审正文；plan 是从已确认正文派生的执行计划，不是第二份需求。可引用/验收条目有唯一稳定 ID；执行上下文带来源、版本及指纹。

权限、金额、条件分支、异常恢复等图示规则必须有文字或表格对应。图文不一致及未定义条件返回 clarify，不靠猜测补齐。派生摘要/图示/plan 随来源变化更新或标过期，不用摘要代替未读取的关键条件，不承诺任意图文自动无损双向同步。

### 9. 模板由用户拥有、可替换

共 **11 个模板**：prd、design、plan、clarify、research、check、rule、memory、spec、user-index、project-index。专题比较/变更分析并入 research 可选章节；test-cases 暂缓，review-log 移除，UI 两份模板暂不保留。

prd/design 使用个人仓库 `zyf3313/fstar-trellis-ext` 固定提交 `674bea37cf2f6f25cd20dab93e1a54ae1f13ce66` 的模板及 profiles，适配清单见 `research/personal-template-review.md`。design 第 7 章为“影响范围”，仅列受影响模块/功能及影响，不列代码文件/函数，也不塞入原测试执行表；原配置、附录顺延为第 8、9 章。PRD 验收、plan 验证和 check 测试职责继续保留。

模板解析优先级：任务显式指定 > 项目模板 > 用户模板 > 安装包默认。保留语义槽位（artifact_type/version/review_state/author/date/reviewer）、稳定 ID 与关联，不强迫固定标题或 ID 写法；首次映射可由 Agent 辅助并经用户确认，程序不能语义猜指针或批准。模板来源与版本可追踪，升级不追溯改写已评审产物；改模板只影响今后生成，改产物只影响本次文档。

### 10. 评审稿：单一内容源

规划评审包按需建立 `doc/prd.md` 与 `doc/design.md`。用户审阅、讨论确认后，启动记录绑定当时范围与指纹；不要求再批准一遍执行计划。文档的 review_state/冻结记录只表达真实用户确认，编辑完成不能自动标批准。

同事可通过文件夹阅稿，其意见由用户转述并保留来源，不能替代用户批准。预览使用现有阅读器或对话展示；第一版无评审工作台、多人在线评审或 Storybook 产品交付。底层需求/方案变更事件留在 events[]，不生成独立 review-log。

### 11. 文档职责与直接测试

| 产物/环节 | 当前职责 |
|---|---|
| clarify | 参考 OpenSpec explore 进行证据先行、按决策依赖展开的讨论；自行维护任务根 clarify.md |
| doc/editor | doc 只维护任务 doc/，写作全部交后台 editor；按明确结论、来源、模板和范围编写，主 Agent 继续讨论 |
| plan | 用户评审确认后自动读取有效正文、研究和规范，自行生成/刷新 plan.md；范围/方案/拆分的未决项返回 clarify |
| execute/implement | 主 Agent 按计划协调，实施全部派原生子 Agent；依赖满足且写入/共享资源无冲突的项可以并行 |
| check | 独立检查正文一致性或实施结果；直接补测试、运行验证，可自修生产与测试代码，写实际检查报告 |
| research/learn/init | 分别维护调研、已授权知识与接入索引；不统一交 doc 落笔 |

clarify.md 默认骨架为背景与目标/开放问题/候选方案与取舍/已确认结论/下一步/相关资料；区分事实、建议、未决、被替代结论，旧结论简记替代原因。个别事实记来源即可，多来源比较、工具探测、协议版本研究或方案取舍才创建 research 文件；clarify 记结论与链接，research 存详细依据。

editor 可根据阶段性明确结论后台写作；同文件排队，派发绑定讨论版本，旧稿不能覆盖新结论。讨论结束后收齐稿件，按最终结论整体核对，再由 check 独立检查一致性；修正后交用户评审。已批准且范围未变的文档同步不重新增加审批。

plan 使用 ECC 的 Summary/Patterns to Mirror/Files to Change/Tasks/Validation/Risks/Acceptance 骨架，结合 OpenSpec 的输入依赖核对、结合代码拆任务、逐项验证及分组检查；补任务 ID、优先级、前置依赖、并行条件、来源 ID/指纹。主 Agent 单点维护执行进度、当前动作与阻塞摘要，worker 回报而不并发写 plan。每项有完成判据，每组有测试及文档责任，最后整体集成验证。

check 直接依据 prd/design/plan、实际代码和适用规范验证；测试预期来自需求，不能照抄实现行为。不要求独立用例文件、用例审批或批准指纹。检查报告记录范围/基线、需求或 plan 项到测试路径/标识/运行证据的映射、五态结果（通过/失败/阻塞/跳过/未执行）、修复、真实命令、环境/run id/版本指纹、耗时和重跑次数。未运行或缺证据不能记通过。

每轮检查限定 plan 项、基线、关联影响与结束条件。交 check 后实施者暂停写同一范围，无冲突工作可继续；check 自修后重跑受影响测试和回归，共享接口/配置/依赖变化扩大验证。最终做整项需求检查，不用局部复查代替。无进展或环境阻塞返回原因与尝试记录，必要时进入 debug；不以超时为通过，不编造耗时。多 check 并行、恢复原检查者作为后续优化，不是 v1 必需能力；自修不要求递归再派检查者。

### 12. 最小内核 + 扩展包

默认在任意目录执行“澄清目标 → 执行 → 基础检查 ↔ 修复 → 用户确认”，无轻量/正式二分类或自动升级判定器。三条底线不可裁：实施与检查分离、失败必修复复查、完成仅用户确认。

**默认不落盘指不创建 fstar 工作流元数据**：不初始化 `.fstar/`、不建任务目录/凭证链/路由状态，不承诺恢复；不禁止为用户任务写必要的产品代码、测试或交付文件。基础 implement/check 原生角色仍可执行，不能以未加载扩展包为由改成主 Agent 自己实施。

会话路由节点 `clarifying/executing/checking/fixing/awaiting_user` 只在内存中。五个扩展包各自授权，默认整包，可明确裁剪：

| 包 | 触发信号 | 加载内容 |
|---|---|---|
| 规划评审包 | 范围复杂、需要评审 | clarify 讨论记录、按需 prd/design、plan 及文档维护；仅创建授权产物 |
| 持久任务包 | 跨会话、暂停恢复、追溯 | task.json、三态、证据、租约、events、恢复与归档 |
| 多 Agent 包 | 需要并行实施、独立研究或增强协作 | 四角色协作协议、版本注入和变更传导；基础实施/检查分离不以此包为前提 |
| 项目治理包 | 需要长期复用，项目已 init | specs 主题治理、knowledge、rules/memory 与 learn |
| 工具能力包 | 默认工具不足、指定工具 | 五契约、绑定、Python 分类器、验证与降级 |

安装包 `runtime/routing.md` 是主 Agent 路由唯一来源，由 session-context 注入：识别信号、说明收益/代价、一次推荐一个最高价值包，同意后调用对应 skill；拒绝后继续最小闭环，无新事实不重复问。已有授权直接复用。各包不隐含其他包授权；规划文件可获准落盘而不创建 task.json。中途启用持久任务包从 planning 建立记录，保存已有有效成果并按授权/证据推进，不重做有效工作。

持久化启用后，扩展授权记 `extensions[]`（id/enabled_at/source/scope/included/excluded/reason），启用、裁剪和停用历史记 events[]；此前只存会话上下文。extensions[] 与记录工具 provenance 的 capabilities[] 分离。

**12 个 skill**：核心自动 execute/check/debug/help；评审后自动 plan；协商路由 init/clarify/doc/continue/archive/learn/tools。无独立 recall 或 UI skill。每个宿主同一流程默认一个手动入口，支持 skill 调用时直接用，否则适配 command/prompt/workflow；不再一律生成同义命令别名。help 按安装包入口索引和实际配置只读回答。

**4 个 hook**：session-context、worker-context、worker-result、doc-change；无 turn-context。路由只做调用前判断，不承载任务数据、skill 详细流程或验收硬校验。规则第一版内置，不允许用户/项目覆盖。

## 统一语言规则与知识格式

Skill 执行指令与 routing 以英文为主，description 精简中英双语、每条 ≤200 字符；不维护两套完整正文。对话默认中文且遵循用户当前语言要求；任务产物（含 plan/research/check）默认中文、按项目配置覆盖。规则、记忆内容英文；specs 默认英文、项目可覆盖，init/learn 一致遵循。符号、路径、命令、API、schema 键与稳定 ID 不翻译。

rule/memory/spec 统一 `fstar.knowledge.v1`：共用 schema/type/status；rule 专属 strength=enforced|default；memory 专属 kind=preference|lesson、trust=confirmed|unreviewed；status=active|superseded；spec 无额外专属字段。只维护一份安装包 references/knowledge-format.md。加载器过滤 superseded 与 unreviewed，非法/缺失值明确报错。rule 正文使用简短 MUST/NEVER/APPLIES/NOT/SOURCE，memory 为内容+APPLIES/NOT/SOURCE；不兼容 ECC 存储或 Cursor 规则格式。

用户索引列规则主题/强制性/路径、记忆主题/kind/路径及定制入口；项目索引列概况、规范主题/适用/读取条件/权威路径、长期知识入口和已有权威文档并声明其优先。索引不复制正文，learn 写入时同步索引和引用。

## 任务拆分（不分期，第一版一次性建完）

| 子任务 | 优先级 | 前置 | 交付物 |
|---|---|---|---|
| core-commands | P0 | — | 三态命令、26 字段 schema、证据/租约/验收/扩展授权 |
| project-layout | P0 | core-commands | 三级目录、配置优先级、init 与索引/主题结构 |
| workflow-content | P0 | core-commands、project-layout | 12 skills、4 角色卡、11 模板、路由及语义映射 |
| runtime-hooks | P0 | core-commands、project-layout、workflow-content | 4 hooks 与两宿主适配 |
| runtime-dispatch | P0 | core-commands、workflow-content | 原生派发、并行协调、变更传导、结果回收和限次重试 |
| tool-binding | P1 | core-commands、project-layout | 5 能力契约、tools.yaml、绑定解析与降级 |
| tool-classifier | P1 | tool-binding | Python 确定性分类、注册表/探针、三层验证 |
| knowledge-base | P1 | core-commands、project-layout、workflow-content | context/references、统一知识格式、learn 治理 |
| package-install | P0 | project-layout、workflow-content、runtime-hooks | 包安装/更新/迁移、资源版本/哈希保护、doctor |
| e2e-verify | P0 | 以上全部 | 最小闭环及持久主子任务的两宿主整体验证 |

依赖优先于优先级；并行还需检查写入与共享资源冲突。执行细则及集成验收编号见 `implement.md`。

## 与 Trellis 的关系、来源与约束

Trellis 仅为参考：协议/传输分离、平台适配、jsonl 上下文清单、目录归属、按月归档及主题索引读取条件可借鉴，不复制源码或逐字节继承格式。借鉴思想与复用受许可内容分开判断，若实际使用第三方模板/资源须保留来源并核对许可，不能仅凭“自研”声明得出全部许可结论。

来源索引：`research/policy-decisions.md`（确认与替代轨迹）、`data-formats.md`（格式审计）、`three-lists.md` / `trellis-inventory.md`（上游盘点）、`architecture-map.md`（架构参考）、`tools-capabilities.md`、`knowledge-base.md`、`directory-proposal.md`、`hooks-skills-templates.md`、`skills-detailed.md`、`review-workbench.md`、`personal-template-review.md`、`openspec-explore-comparison.md`、`openspec-plan-comparison.md`、`trellis-execution-check-review.md`。研究文件中未刷新的旧规则只作历史，`architecture-map.html` 按用户要求保留，不作当前权威。

## 非目标（第一版）

自定义 hooks、Claude Code/Codex 之外平台、monorepo package、peer-process runtime、扩展市场、长期 UI 设计资产/原型库、Storybook/评审工作台/多人在线评审、独立测试用例文档及审批包、独立 review-log、自动安装工具、AI 工具分类、自动依赖调度器均不在第一版范围。

## Acceptance Criteria

- [x] 上游盘点、独立实现路线、存储及授权边界已明确。
- [x] 三态/归档命令、证据与验收、五扩展包、五能力、12 skills/4 hooks/4 角色/11 模板已确认。
- [x] 规范主题治理、统一知识格式、模板来源、语言与文档/实施/check 分工已确认。
- [x] 十子任务范围及实施授权已明确，父 design/implement 收敛为当前依据。
- [ ] 全部十子任务实施并通过对应验证，子任务开工时刷新旧文档。
- [ ] `implement.md` §4 的集成验证完成，实际结果与未覆盖项有证据。
- [ ] 父任务整体验收由用户确认，满足归档条件后整体归档。

## Open Questions

当前无须重新讨论已批准产品范围。固定政策已写入设计；常规技术默认值和子任务实测事项见 `design.md` §9。出现影响范围或既有决定的真实冲突才回到用户，技术实现细节由执行者按契约解决。

## Notes

本文只保留现行规则。状态/技能/模板演变、用例审批撤回、doc 职责调整等历史查 `research/policy-decisions.md`，不在执行正文重复旧约束。
