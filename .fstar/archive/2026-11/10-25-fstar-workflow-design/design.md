# fstar 技术设计

父任务 `10-25-fstar-workflow-design` 的当前跨子任务契约。用户已批准最终规划并授权全部十个子任务实施；子任务开工时刷新旧文档，未变范围不重复审批。本文保留原 §1–§9 与 §3/§4 子节编号，供既有引用继续定位；历史方案见 `research/policy-decisions.md`，研究稿的旧正文不构成现行约束。Trellis 父任务计划仍为 `implement.md`；产品任务计划为 `plan.md`。

## 1. 设计目标与边界

### 1.1 fstar 要解决的五个问题

跨项目保留个人工作方式；以证据与用户验收代替 Agent 自称完成；以能力契约/用户绑定适应工具差异；完整读取适用规范同时控制无关上下文；以默认最小闭环和独立扩展授权避免无必要的工作流负担。

产品独立实现，Node CLI + Python 脚本打包。Trellis 只提供设计参考，不依赖其安装、不复制源码或数据格式。宿主 v1 为 Claude Code 与 Codex，原生子 Agent 执行，协议与传输分离。角色边界是执行协议与宿主权限约束，不能宣称角色文本构成安全沙箱。

### 1.2 明确的非目标（第一版不做）

自定义 hooks、其他宿主、monorepo package、peer-process runtime、扩展市场、长期 UI 设计资产/原型库、Storybook/评审工作台/多人在线评审、独立 test-cases 文档及审批包、review-log、自动安装工具、AI 工具分类、自动依赖调度器、多 check 并行及恢复原检查者优化。

## 2. 总体架构

### 2.1 七层

| 层 | 当前组成 |
|---|---|
| 触发 | 4 hooks：session-context / worker-context / worker-result / doc-change |
| 编排 | 主 Agent + research / implement / check / editor 四角色 |
| 能力 | 12 skills：核心自动 4、评审后自动 plan、协商路由 7 |
| 工具 | 5 能力契约 + 用户绑定 + Python 确定性分类器 |
| 产物 | 11 模板，prd/design 可替换并映射语义槽位 |
| 存储 | 安装包资源、用户级内容、项目级数据、嵌套任务树 |
| 底座 | 最小闭环；启用持久任务包后用命令维护三态/证据/租约/验收 |

上层调用下层公开契约，核心状态/存储不依赖 skill 文本或具体宿主。最小闭环仍由 implement 和独立 check 原生角色执行，主 Agent 沟通协调；没有 inline 回退。

### 2.2 三条数据流

- 会话：宿主入口→识别项目/会话→读索引、当前任务及已启用包→注入安装包 `runtime/routing.md`。先完整掌握概况/索引/全局约束，再按工作范围加载全部适用规范正文。
- 任务：授权的最小闭环执行，或启用持久化→task create→start→实施/check 自修复查→用户 accept→archive。读写任务的关键边界重新核对来源/版本/租约。
- 工具：维度需求→解析绑定→三层验证→调用/记录→缺口报告与降级。扫描与实际调用分开，发现不等于授权绑定。

### 2.3 三级存储

| 位置 | 内容与所有权 |
|---|---|
| 安装包 | CLI/Python、skills、roles、4 hooks、routing、模板/映射、references、能力契约、注册表、schema |
| `~/.fstar/` | 用户 config/index/rules/memory/tools、模板/skills/workflows 定制、identity、版本/资源基线、runtime |
| `<项目>/.fstar/` | config/index/schema-version、specs、knowledge/context 与 references、tasks/archive、项目 tools/template 覆盖；仅数据 |
| 宿主用户目录 | skills/agents 与必要的入口适配、hook 注册；安装器仅管理自身文件/配置条目 |

运行态与可版本控制内容分开；会话 current pointer 在用户 runtime 下按项目身份+会话 ID 隔离，不存在一个全局当前任务。无可核实会话身份时读取可用，写 current/接管等需明确目标，不能覆盖别的会话。

### 2.4 最小内核 + 扩展包

默认“澄清→执行→基础检查↔修复→用户确认”。会话节点 `clarifying/executing/checking/fixing/awaiting_user` 只用于路由、不持久化、不承诺恢复。**不落盘指不写 fstar 元数据，不禁止授权任务需要的代码/测试/交付文件写入**。

| 扩展 ID（实现默认） | 内容 |
|---|---|
| planning-review | clarify、按需 doc/prd 与 design、plan、后台 editor 与文档检查 |
| persistent-task | task.json、三态、证据、租约、events、恢复、整树归档 |
| multi-agent | 增强协作、并行实施、独立研究、版本注入和变更传导；基础 implement/check 分离始终可用 |
| project-governance | 已 init 项目的主题规范、knowledge、个人 rules/memory 与 learn |
| tool-capability | 五能力、绑定、分类、验证、降级 |

各包默认整包、允许明确裁剪、互不隐含授权。一次只推荐一个最高价值包并解释代价；拒绝后无新事实不重问。包 ID 是统一技术默认，不改变产品包的语义。裁剪按包清单中的具名能力验证，included/excluded 不重叠，不可裁三条底线；停用只停止后续能力，不删除已有资料或在途记录。

未启用 persistent-task 时授权留会话；规划评审包可按授权建产物目录，但不隐式创建 task.json/租约。持久化启用时一律建立 planning 记录、导入已有有效成果和确认来源，再按命令校验推进，不重做有效工作。未启用规划评审包不强制 doc 文件，持久任务仍需明确任务目标/验收范围及真实检查证据。

## 3. 核心机制设计

### 3.1 状态机：三个维度

phase（进度）、evidence（支持且可失效）、lease（在途所有权）独立。正常 phase 枚举只有 `planning | in_progress | completed`。

| 操作 | 条件与结果 |
|---|---|
| create | 持久化获授权后建 planning；检查目标路径冲突 |
| start | planning→in_progress；核验用户实施授权、有效规划/plan 和阻塞条件；启用规划评审时确认绑定 prd/design 指纹 |
| 实施/check/修复 | 留在 in_progress；通过角色、报告、证据区分动作，不加 phase |
| 回规划 | in_progress→planning；原因写事件，已有证据全 stale、旧验收失效、释放租约；使用 continue 的显式回规划动作 |
| accept | in_progress→completed；用户确认来源、新鲜独立 check 通过、交付指纹、无在途工作/阻塞/未决正确性问题、子任务条件均满足 |
| 证据过期 | 受影响证据 stale；若完成依据失效，有效状态回 in_progress，历史确认保留；planning 的草稿不因失效自动开工 |
| 验收否决 | “改改”继续 in_progress；“方向错了”回 planning；不明确才澄清 |
| archive | completed 整树移入 archive/<YYYY-MM>/，记录 archivedAt；非 phase；检查目标冲突并绑定归档授权 |
| drop / revive | 用户决定遗弃/复活；遗弃戳在 meta.disposition，phase 不加第四个值；原因与现场处置必填；未归档的遗弃任务可按用户授权回 planning |

`blocked` 保留 `{reason,since}`；设置者、解除来源与核验依据在事件中记录。Agent 不自写自解，用户设的由用户解；前置依赖完成只触发重新核实，不自动解除或派发。使用 continue 的显式处理动作复用命令面，不恢复任意 state set。

容器有效进度取未遗弃子节点最靠前非终态，计算不另存聚合字段；子节点全 completed/dropped 后容器仍须整体检查和用户验收。容器自己的规划/批准信息保留，不能因子任务在干活而伪造其验收。

整树归档要求当前有效 completed、所有子节点 completed/dropped、当前验收所依赖的证据新鲜、无未决问题；旧 stale 报告可保留历史，不要求删除历史才归档。未归档完成任务由用户重开时回 in_progress；归档后的新需求新建关联任务，不搬回原树。

### 3.2 证据与指纹

采用 **条目级 SHA-256 内容哈希**（算法为实现默认，条目级粒度是已定政策）。`validates[]` 每项含 artifact、items[]（稳定 ID）、各条目内容哈希；另绑定实际交付代码/测试/相关配置基线。没有结构化条目的输入按文件快照绑定，不能以虚构 ID 减少覆盖。

证据含 id、kind、producer/role、produced_at、state(valid|stale)、verdict、validates、delivery、report_ref、run_id、环境及结果引用。check 证据必须来自独立 check 角色，角色信息与派发记录交叉核对，不能把 implement 自检当独立检查。未执行/失败/阻塞/跳过不等于通过。

改 R-001 只失效引用它及其依赖的证据；无法确定影响关系时保守扩大并说明原因。改代码/测试/共享配置同样核对被检查版本，不能只哈希文档。回规划使全部当前证据 stale。schema/路径/哈希完整性可程序检查，语义是否覆盖需求由 check 判断，不能声称哈希证明实现正确。

检查报告先原子写完，再在任务锁内验证版本并提交引用；中断留下的未引用报告不算有效证据。任务 events 与状态在同一 task.json 事务更新。读取、派发、恢复、回收、验收、归档重算关键指纹，补足外部编辑绕过 hook 的情况。旧结果保留但不能被标成新版本通过。

无顶层 review[]、无独立用例批准证据前置；规划批准在启动事件及其 source/指纹中。保留通用 review record/list 的中途产物记录能力，不恢复测试审批流程；review 记录不能替代最终 acceptance。

### 3.3 租约

同任务单写者：holder/acquired_at/expires_at/takeovers[]。默认 30 分钟，有效 worker 回报自动续约 +30m。写命令在短期文件锁中校验 holder 和当前版本，再临时文件+原子替换；过期不等于可静默重派。

主 Agent 持任务协调租约，worker 通过回报提交状态请求，不直接并发改 task.json/plan。不同子任务可独立租约并行；同任务多 worker 的文件范围由主 Agent 分配。交 check 的范围停止 implement 写入，共享文件或资源冲突必须串行或明确隔离；worktree 不能自动消除逻辑依赖。

continue 对孤儿租约先只读核对状态、遗留产物及真实 worker 情况，再报告用户决定接管/重派/放弃；接管记录旧 holder、原因、新 owner，旧租约失效。不能把状态恢复称为 worker 上下文恢复。

### 3.4 验收闸门与确认来源边界

acceptance 至少包含 confirmed_at、confirmed_by=user、source、evidence_refs[]、validates/交付指纹。source 类型沿已定 `command | conversation | review`：记录可定位的宿主用户输入/命令执行来源、原话或记录引用、时间、确认范围及当时指纹；review 必须回链可核验的用户确认，不能只相信文件的 approved 字样。来源缺失、内容与授权范围不符、指纹 stale 时命令拒绝，并说明缺项。Agent 可以代记真实用户已表达的确认，不能自称用户。

**可信边界**：CLI 能检查结构、来源引用、角色记录、状态和新鲜度；同一系统权限下有 shell/文件写权限的 Agent 也可能调用 CLI 或篡改记录。`source: command`、confirmed_by=user 或 Agent 自报身份都不是不可伪造证明。只有宿主实际提供且可核验的用户输入来源才增加可信度；v1 不宣称具有阻止此类伪造的安全隔离，不新增签名服务/独立审批系统。测试验证缺来源、错范围、过期来源被拒，不能写成“Agent 在任何情况下无法伪造用户”。

### 3.5 能力契约 → 绑定 → 工具

五 ID：code-structure/web-research/knowledge-retrieval/data-access/test-execution。契约七段：定义、判定要点、三层验证、推荐实现、常见不合格实现、降级、记录要求。判定要点须可检测，不能用产物质量描述工具能力。

tools.yaml 记录 detected_at、工具及其版本、匹配 match=strong|weak|none、绑定与确认来源、变更历史。绑定解析按项目>用户>默认，按事项覆盖，不因存在项目文件就丢弃所有全局绑定。provenance 进入 capabilities[]，与扩展授权独立。缺能力报告实际缺口、验证失败原因及降级路径，不自动安装或更换绑定。

### 3.6 Python 分类器

L1 清点 PATH/MCP/skills→L2a 注册表 strong→L2b 通用探针 weak→L2c 手动未分类候选。用户 registry.d 优先于安装包注册表。AI 不进入分类路径；自然语言解释提案不参与分类判断。

三层可用性验证分别报告可发现、客户端加载、最小真实调用；根据具体维度选安全且最小的调用，不把代码符号查询范例套到数据写操作。扫描应只读，不自动执行任意未知工具自述命令。确定性测试使用固定输入快照，时间戳独立处理，不能要求两次实时时间戳相同。

完整扫描仅 init/tools scan；session-context 只查已有绑定存在性与 detected_at 过期，不做完整探测。工具能力包未启用时 init 可完成接入并提出启用建议，未确认不写绑定。

### 3.7 派发协议

主 Agent 使用宿主原生 Agent 工具实际派发；CLI `dispatch` 准备/校验协议数据与登记，不能凭空承诺 shell CLI 能调用当前会话原生工具。适配器负责宿主工具参数及回收，宿主不支持必要能力时明确报缺口，不退回主 Agent 写生产代码。

派发最少字段：dispatch_id、task_ref（最小闭环可为 session 引用）、role、plan_item_ids、baseline、输入版本/指纹、allowed_paths、read_context、必需验证、完成/阻塞/失败返回条件。持久任务提示词以 `Active task: <路径>` 开头；无持久任务明确 `Active task: session-only`，不捏造目录。

结果含 dispatch_id、role、status、changed_paths、产物引用、验证事实、耗时/重跑数、阻塞、输入/交付基线；回收核对派发身份、当前版本、授权范围及租约再写证据。worker done 只表示回收完成，不等于验收。

对话变更与文件变更统一形成带 change_id、来源、受影响条目/计划项、旧/新指纹和动作的变更消息。宿主支持实时转向则传达并确认；不支持时暂停受影响范围，在检查点回收并重派，旧结果只留历史。正确性不依赖向运行中 worker 实时传话必定成功。

派发失败最多自动重试 **1 次**，附上次原因；仍失败停止派发进入 debug。跨会话 continue 只读发现孤儿后等待用户决定，不能自动重派。按依赖与写入/共享资源约束并行实施，优先级不越过依赖，无独立调度器。

### 3.8 Hooks

| Hook | 语义触发 | 动作/边界 |
|---|---|---|
| session-context | 会话启动/clear/compact 的宿主等价事件 | 数据读项目/用户索引和当前任务；规则读 routing 全文；只做绑定失效/过期轻检查 |
| worker-context | 原生派发前 | 按角色完整加载适用上下文，带文档版本/指纹、范围及计划项 |
| worker-result | 完成/失败/取消回收 | 核对基线并登记交付，路由检查或 debug；不写用户验收 |
| doc-change | doc/*.md 编辑后 | 幂等重算指纹、相关证据 stale、记录事件、提示变更传导；不跑测试/写报告 |

没有 turn-context。没有 task.json 时任务簿记静默跳过且不建文件，最小闭环路由仍生效；显式任务 CLI 缺数据则清楚报错，不能静默伪装成功。planning 中无既有证据不产生 stale 噪声；已有证据无 phase 豁免。

具体宿主事件名/input schema 由 runtime-hooks 实测确认，不能将一平台事件名写成两平台保证。宿主缺少事件时用派发/回收/命令边界执行同一逻辑并报告覆盖限制，不另加第五个 hook。learn 候选入口挂现有会话/结果/恢复/归档节点，语义判断在 learn；不增加每轮扫描或独立候选文件。归档巡检仅 archive。

### 3.9 知识库

仅 knowledge/context、knowledge/references；长期决定归 specs，无 decisions/history/journal。历史视图用 task list --archived 动态派生，回忆由 routing 处理，continue 不承担历史总览/归档提醒。

rule/memory/spec 统一 `fstar.knowledge.v1`：必需 schema/type/status；rule 必需 strength=enforced|default；memory 必需 kind=preference|lesson、trust=confirmed|unreviewed；status=active|superseded；spec 无专属字段。非法/缺失取值报错，不静默默认。superseded 和 unreviewed 不加载；memory 不自动升级规则。

英文 rules/memory；specs 默认英文可由项目覆盖。rule 正文短断言 MUST/NEVER/APPLIES/NOT/SOURCE，memory 内容+APPLIES/NOT/SOURCE。只维护一份 references/knowledge-format.md，context/references 遵循项目语言策略，不强行变成规则 schema。

加载先过滤有效性与适用范围，再裁决 enforced rule > 项目明确规范 > default rule > confirmed memory，冲突显式说明；项目已有权威文档优先于 fstar 派生规范。实际读取遵循全局概况/全索引/全局约束→适用主题及上下游/共享契约正文，范围不明扩大读取。

learn 按已授权内容/归属写入，未确认先呈现候选；明确授权不重复问。正文+索引+引用作为一组更新，先暂存与校验、失败恢复原内容、完成后才报告成功；同文件单写者。可修正、替换、淘汰及重命名，所有引用同步，不自动扩大适用范围。主线程忙/整理复杂时使用通用后台 Agent，空闲小改直接执行；不新增 learn 角色。候选暂缓留任务依据，不阻塞合法归档。

### 3.10 评审稿：人机共用的唯一内容源

规划产物 doc/prd、按需 doc/design；任务根 clarify、plan；按需 research；实际检查报告 acceptance/check-<n>.md。文档语义槽位为 artifact_type/version/review_state/author/date/reviewer，所有被引用/验收条目有稳定唯一 ID 和明确关联。review_state 不是验收状态，不能从编辑动作设为已批准。

模板可更换标题/布局/语言/图示/ID 写法；任务>项目>用户>默认。映射显式声明槽位、条目 ID 与引用的提取规则，不能猜指针。模板来源/ref/hash 记 meta.templates，不新增顶层字段。模板升级不重写旧产物，首次映射可由 Agent 辅助并按用户授权保存。

prd/design 模板来自个人仓库提交 `674bea37cf2f6f25cd20dab93e1a54ae1f13ce66`，profiles 是参考文件不是第十二份模板。design 第7章改“影响范围”、原第9/10章顺延第8/9章，详见 personal-template-review.md。当前父设计为跨子任务契约，不在本次强套产品默认模板重排编号。

plan 读取已确认正文、采纳研究、规范和相关代码/测试，使用 ECC 七段骨架并补 ID/依赖/优先级/并行/验证/来源指纹。每项明确完成判据，每组明确测试和文档责任；来源变更只补受影响部分；图示关键分支/异常转成文字规则，歧义返回 clarify。用户评审即放行，plan 有效无阻塞后 execute，无额外计划批准。

check 直接审查、补测试并运行，允许本范围生产与测试自修，不能改变需求或测试预期掩盖缺陷。报告覆盖 plan 项、需求/设计条目、测试路径/标识、真实命令/结果/环境/run id/基线及未覆盖项；五态通过/失败/阻塞/跳过/未执行。无测试用例文档或审批前置。修复按影响复查，最终整体检查；无进展返回原因，耗时可见，不编造数字或反复全量审查无关历史变更。

### 3.11 规范按主题归口

init 探索整个项目的实际结构与已有权威资料，缺背景才提问，按主题建立职责和读取索引，不预设所有项目为前后端。learn 先读索引和候选正文，优先更新已有主题，新增/调整须理由；共同规则一处正文、多处引用，不设文件数上限。

用户索引：规则主题/强制性/路径、记忆主题/kind/路径、本地定制入口。项目索引：简短概况、主题/Applies to/读取条件/权威路径、context/references、已有权威资料优先声明。索引只导航不复制正文。写作参考 Trellis 简明、可执行、有依据的规则，必要短示例，不添加固定多栏目骨架；结构/链接脚本检查与语义 Agent 检查分开。

### 3.12 文档一致性与维护

clarify 自己维护 clarify.md；doc 专管 doc/，写作全部派后台 editor；plan/check/research/learn/init 各自维护所属产物。editor 只改派发指定文件/条目，不自行增删 ID 或裁决需求/批准；缺信息回报，不能擅自补全。

同文档编辑排队，派发绑定讨论修订与基础哈希；提交前核对当前哈希，不匹配返回主 Agent 合并/重派，禁止旧稿覆盖新结论。editor 回读检查槽位、ID、关联、图文，并回报更改和未决；check 承担独立一致性检查，复用同一 checklist。整体讨论结束收齐结果，依据最终结论整体核对后评审；已授权未变范围的同步不重开批准。

hook doc-change 管幂等簿记，doc 管来源/写作/回读，editor 管限定范围落笔；execute 负责变更协调。外部编辑由核心边界重算补足，hook 不能代替新鲜度校验。

## 4. 跨子任务接口契约

### 4.1 CLI 命令面

所有操作提供结构化 `--json`；失败非零、原因可读，JSON 模式返回稳定 code/message/details。生命周期命令收敛后不提供任意 state set，不把内部存储函数逐一暴露成用户命令。以下按命令族列，不沿用历史“13条”的混合计数。

| 命令 | 契约 |
|---|---|
| task create / list / current | 创建授权任务/查询；list 支持 --active/--archived/--all 与可选 --query；current 会话隔离 |
| start | 核验启动授权与规划有效性，planning→in_progress |
| accept | 核验用户来源、新鲜独立 check、当前范围与子任务条件，写 completed |
| drop | 用户决定，必含原因与保留/丢弃/转知识处置；复活为该命令的显式动作 |
| archive | 整树归档、目标冲突检查、archivedAt；成功后调用归档巡检逻辑 |
| state show | phase/blocked/evidence/lease/extensions 与派生待验收标记，只读 |
| continue | 恢复核实、差异报告；显式接管/回规划/阻塞处理；孤儿不自动重派，无归档巡检 |
| extension list / enable | 五包及 full/custom 范围；裁剪/停用由同一族显式动作承载，授权来源与事件同步 |
| dispatch implement\|check\|research\|editor | 准备/验证派发协议与登记，实际派发由原生适配器完成 |
| interrupt | 变更传导、取消或检查点停止；保留原因与基线 |
| doc-edit | 指定 doc 文件/条目的 editor 协议入口，不是直接改写任意文件 |
| tools scan | 显式全量扫描；验证/状态由工具模块及 tools skill 复用，不另造自动安装路径 |
| review record / list | 可选中途产物记录；不恢复用例审批要求，不作为测试前置 |
| evidence invalidate | 按文件/条目重算并失效；证据添加与租约更新为派发/回收内部事务 |
| acceptance status | 当前验收覆盖、五态结果、基线/环境/run id/证据来源 |
| init | 接入骨架、现有资料引用、主题索引、首次绑定提案；不覆盖用户资料 |

package-install 管安装/更新/卸载、doctor、migrate、version，属于发布管理面。doc check/spec check/inspect/reminder 独立命令不保留：对应校验归 doc/check、learn、continue、archive。内部 API 可供 hooks 调用，不据此再扩一组面向用户的生命周期命令。

无隐式 git 操作，auto_commit=false。显式任务操作缺项目/任务/授权时说明所缺上下文；只有被动 hook 在最小闭环跳过任务簿记。

### 4.2 数据格式契约

**task.json 权威顶层清单恰为 26 项**（逐项核对 policy-decisions.md 的“权威字段清单26”，早期23为误计）：

```text
id, name, title, description,
phase, blocked, evidence, lease, acceptance,
completedAt, archivedAt, children, priority,
creator, assignee, createdAt,
branch, base_branch, worktree_path, commit, pr_url,
notes, meta, capabilities, extensions, events
```

| 结构 | 约束 |
|---|---|
| name / title | 机器目录名 / 人读名，均保留；路径归一化、拒绝越出任务根 |
| phase / blocked | 正常三态；blocked={reason,since} 或空；设置/解除来源在事件 |
| evidence / lease / acceptance | 见 §3.2–3.4；历史保留，不重复建立顶层 review |
| children | 子目录名引用，目录体现归属；不作为依赖调度字段 |
| meta | 固定用途子键：disposition 遗弃戳、templates 来源映射、related_tasks 历史关联、reminders 暂缓/去重；不新增顶层字段 |
| capabilities[] | 实际能力维度/工具/版本/调用依据 provenance，不能存扩展包授权 |
| extensions[] | id/enabled_at/source/scope(full\|custom)/included[]/excluded[]/reason；当前授权快照，变更历史在 events |
| events[] | 追加式，**软上限200**；最老普通事件可压缩为保留时间范围/数量/必要来源的摘要；评审/验收/归档/扩展启用等里程碑永不清除；里程碑本身超200仍保留 |
| implement.jsonl / check.jsonl | 每行 file/reason，列 spec/research 等规范依据，不列生产代码路径；代码范围由 plan/派发约束 |
| clarify/plan/doc/research/check | 各按 §3.10–3.12 归属；产品 plan，不生成产品 implement.md |
| acceptance/acceptance-<n>.json | 如输出验收快照，以 task.json.acceptance 为权威，可再生/校验；不是第二次独立批准，不以快照存在自证用户 |
| config.yaml / config.local.yaml | 项目>用户>默认，逐项合并；local 仅本机且不入库；沿用 context_injection 的 max_file_bytes/max_artifact_bytes/max_total_bytes |
| .schema-version | 数据格式版本，由显式 migrate 处理 |
| tools.yaml / registry.d | 见 §3.5–3.6；用户 registry.d 优先，绑定未经确认不写 |
| 模板+mapping.yaml | 显式槽位/ID 提取与引用规则、来源版本；缺槽位报错，不推断已批准 |
| rule/memory/spec | 同一 fstar.knowledge.v1，见 §3.9；唯一格式说明 references/knowledge-format.md |

### 4.3 目录布局契约

```text
安装包/
  cli/ python/ schemas/
  skills/ agents/ hooks/
  runtime/routing.md
  templates/{doc,task,knowledge,entry}/
  references/ capabilities/ registry/
~/.fstar/
  index.md config.yaml .identity version .asset-hashes.json
  rules/ memory/ tools.yaml tools/registry.d/
  templates/ skills/ workflows/ runtime/
<项目>/.fstar/
  index.md config.yaml .schema-version
  config.local.yaml                 # 按需，本机配置
  specs/ knowledge/{context,references}/
  tools.yaml templates/             # 按需覆盖
  tasks/<任务>/
    task.json                       # 仅持久任务包
    clarify.md plan.md
    doc/{prd,design}.md              # 规划评审包，按需
    implement.jsonl check.jsonl     # 持久任务派发清单
    research/ acceptance/
    subtasks/<子任务>/...
  archive/<YYYY-MM>/<主任务>/...
```

以上为逻辑发布布局，源码路径可由 package-install 按工具链组织，但公开资源相对路径统一。初始化不生成全部空目录或未确认规则；按已授权包与真实产物创建。已有项目资料优先引用，knowledge/specs 入版本控制，local/runtime 排除；更新不重置用户内容。

归档移动前检查目标；实现需可识别同一次操作的重试，拒绝覆盖另一任务。这是事务可靠性默认，不表示支持重新开发归档任务。采用操作 ID/任务 ID 和目标检查处理“已移动但指针未清”中断；只清引用该任务的指针，不清无关会话。

### 4.4 宿主集成契约

| 项 | 当前约束 |
|---|---|
| 12 skills | init/clarify/doc/plan/execute/check/continue/archive/learn/debug/help/tools |
| 分层 | execute/check/debug/help 核心自动；plan 评审后自动；其余7按授权路由；recall 是意图 |
| description | 每条≤200字符，12条正文合计≤2400；listing 的分隔/名称成本另算，不把字符等同 token |
| 内容语言 | skill/routing 英文为主；description 精简中英双语；任务默认中文；rules/memory英文、specs默认英文可覆盖 |
| 宿主资源 | Claude 用户 skills/agents/settings；Codex 用户 agents/skills/入口按实际支持适配；不是项目级程序副本 |
| 手动入口 | 每流程每宿主一个；支持 skill 手动调用则直接使用，否则生成 command/prompt/workflow；无强制双份别名 |
| hook 注册 | 追加/去重、精确记录自身注册项，不覆盖用户其他设置；卸载只撤自身项 |
| 注入 | 概况、完整规范索引、全局约束、角色清单、权威 prd/design（如有）、plan、全部适用规范与共享契约正文；每个输入带版本/指纹 |
| 体积边界 | 超限可输出索引行和未加载清单，但执行者必须补读适用正文才执行，不能静默截断关键条件 |
| routing | 安装包唯一源，注入数据与规则分开；只含调用前判断，第一版不允许用户/项目覆盖 |
| doctor | 按实际宿主版本检查入口/资源/hook/schema 与 skill listing；无法观察实际 listing 时明确区分估算和已核实 |

listing 研究基于 Claude Code 2.1.311，不作为所有版本保证。name-only 可降低描述占用；user-invocable-only/disable-model-invocation 会影响模型调用，不能为省预算破坏自动路由。安装器不得伪造调用或修改 skillUsage 声称获得预算；可展示真实入口和首次使用清单，具体配置变更须有授权。

**11 个模板清单**：templates/doc/prd.md、design.md；templates/task/plan.md、clarify.md、research.md、check.md；templates/knowledge/rule.md、memory.md、spec.md；templates/entry/user-index.md、project-index.md。mapping/profiles/schema 不作为新增产物模板计数。

### 4.5 子任务 ↔ 契约对照

| 子任务 | 所有权/主要契约 |
|---|---|
| core-commands | §3.1–3.4、§4.1–4.2 的任务存储/命令/来源/证据/租约；单一状态写入口 |
| project-layout | §2.3/§3.11/§4.3 的配置、项目接入、索引/主题规划 |
| workflow-content | 12 skills/4 roles/11模板、routing、映射、共享检查清单 |
| runtime-hooks | 4语义 hooks、宿主事件适配、注入与回收调用核心事务 |
| runtime-dispatch | 原生工具桥接、派发/变更/回收、依赖与写入协调、1次重试 |
| tool-binding | 五契约、tools schema、绑定解析、provenance/缺口 |
| tool-classifier | Python探测、注册表、weak探针、三层验证 |
| knowledge-base | 统一知识schema/加载裁决、learn原子更新、两类长期知识 |
| package-install | 包结构、资源版本/基线、安装更新迁移、doctor、入口索引 |
| e2e-verify | 双宿主最小闭环+持久树+扩展组合集成证据 |

## 5. 关键取舍

原生 Agent 承载传输、协议独立，降低 runtime 范围但承认宿主恢复/转向差异。用户级资源保证跨项目可用，同时承担 listing 成本并由 doctor 报告。任务状态/events 同文件事务，报告和可再生快照不形成第二个状态源。知识先归口再写入，不能靠目录名自动防重复。Python 分类确定可测，但不保证零运行时间或完全识别未知工具。

三态承载进度，角色/证据/命令承载检查和用户验收；因此不增加流程状态来表示每个动作。模板自由与机器定位通过显式映射兼容。最小闭环省工作流元数据，不省独立检查及用户确认。历史取舍详见 policy-decisions，不在本文保留相反规则。

## 6. 兼容与迁移

不迁移 Trellis 数据，不混用其 task.json。CLI 包版本、已安装资源版本、数据 schema 版本分别记录；`.asset-hashes.json` 在用户级记录安装器拥有的资源基线，version 记录所选资源版本，项目配置如指定版本须实际解析到该版本缓存/安装资源，否则明确报版本不可用，不能静默用最新。

更新由显式命令发起、可预览。未改资源可更新；用户修改项提供保留/覆盖/生成 .new，默认保留。只管理安装器拥有内容，规则、记忆、规范、任务、归档不随模板更新重置。迁移先备份、验证、再切换，失败保持或恢复原内容；重命名/删除须同步引用。hook 设置修改以自身条目精确撤销。

## 7. 风险与缓解

| 风险 | 可验证边界与应对 |
|---|---|
| listing 描述被降级 | doctor 依据实际版本/可观察能力告警；显式入口与routing可用性实测，不承诺自动触发必成功 |
| 原生 worker 恢复/转向不支持 | 明确降级为检查点停止；孤儿只读报告等用户决定，不能假报恢复 |
| 批准/provenance 记录伪造 | 核对真实来源、派发与调用记录；不把同权限CLI/JSON宣称安全隔离 |
| 并行覆盖/接口漂移 | 主 Agent单写plan/任务状态；派发限定范围；共享处串行，契约先更新后消费 |
| 旧文档或外部编辑 | 派发带指纹、editor提交前校验、核心关键边界重算，旧结果失效 |
| 模板语义提取失败 | 明确错误，不猜ID或批准；映射与版本绑定 |
| 知识冲突与重复 | 查已有主题/完整适用正文、显式冲突、原子更新索引/引用 |
| 扩展推荐打扰 | 一次一个、拒绝后无新事实不再问；当前授权可恢复 |
| 许可或来源误表述 | 保留实际资源来源并按使用形式核对许可，不用“自研”替代核实 |

## 8. 交付形态与回滚

一次性交付可安装包、12 skills、4角色、4 hooks、11模板、5契约、项目骨架、完整命令及双宿主验收记录。十子任务全部在实施授权内，先后顺序是依赖而非分期交付。

回滚内容资产/代码不删除用户数据；卸载只移除安装器拥有资源与注册项，保留 `~/.fstar/` 用户内容和项目 `.fstar/`。派发故障停止/修复适配器，不回退 inline 实施。迁移有备份；工具绑定和知识修改不能因卸载重置。

## 9. 留待各子任务定的事项

以下为已选技术默认或需实测的实现细节，不是待重新批准的产品范围。

| 项 | 当前默认/执行责任 |
|---|---|
| 哈希与原子IO | SHA-256；任务文件锁+临时文件原子替换；core-commands实现并测并发/中断 |
| 固定限额 | 条目级指纹；events软200且里程碑永存；租约30m、有效回报续30m；派发最多自动重试1次；不得重开讨论 |
| 事件类型 | started/replanned/blocked/unblocked、evidence_added/invalidated、lease变更、review/acceptance/drop/archive、extension变更、doc变更；使用统一带ID/at/source/type/data封套 |
| 遗弃/历史关联/提醒落点 | meta.disposition / meta.related_tasks / meta.reminders；不增加顶层字段，关联不等于依赖 |
| 归档提醒阈值 | 可配置技术默认30天无活动；去重键=任务ID+状态/缺项摘要+最近活动版本，默认暂缓7天；仅archive运行，所有值与时间依据可见，不将阈值说成用户指定 |
| 配置语言 | 复用config中的language.interaction/artifacts/specs键，默认zh-CN/zh-CN/en；知识rules/memory英文；字段为技术默认 |
| 正文映射 | workflow-content选定可解析的默认锚点/映射语法；必需槽位和稳定ID保持，发现实际模板缺项明确报错 |
| 宿主适配 | runtime-hooks/dispatch实测事件、消息、取消、权限及跨会话行为；缺能力报告，不虚构等价 |
| worker权限 | 使用用户已选无交互worker执行模式，仍遵循宿主实际权限；不通过模式切换扩大主会话被拒范围 |
| 资源固定/哈希 | SHA-256基线；package-install落实实际版本缓存/选择、冲突与可恢复迁移；具体工具链模块组织在其子设计定 |
| 语义与脚本分界 | 脚本管schema/路径/引用/指纹；check/learn管语义完整性及重复，不声称脚本全懂自然语言 |

参考来源：policy-decisions.md（决策、固定限额）、data-formats.md（格式盘点）、tools-capabilities.md、knowledge-base.md、directory-proposal.md、hooks-skills-templates.md、skills-detailed.md、review-workbench.md、personal-template-review.md、openspec-explore-comparison.md、openspec-plan-comparison.md、trellis-execution-check-review.md。`architecture-map.md` 是架构参考，HTML 按用户要求保留且不是当前权威。只有新事实揭示范围/批准决定冲突才回用户，其余技术实现按本契约推进。
